"""
rag.py
======
Retrieval layer for brand standards.

Why this exists (business framing):
BroadPeak's portfolio spans very different brand types -- a golf & hospitality
property (Wolf Creek), a fast-casual restaurant (Roti), a gifting franchise
(Edible Arrangements), etc. A single hard-coded checklist and prompt would
either be too generic to be useful, or would need a code change every time a
new brand or a brand's standards get updated.

Instead, each brand's written standards live as small text documents in a
ChromaDB collection. At findings-generation time we retrieve only the
standards relevant to the specific category being audited (e.g. "Course
Conditions" for a golf property) and hand just that slice to the LLM. This:
  - keeps prompts short and cheap (only relevant standards, not the whole
    brand manual, on every call)
  - lets a franchise-ops team update standards by editing/re-embedding text,
    with zero code change
  - scales the same agent code across hundreds of locations with different
    brand standards, which is one of the key questions in the brief.

For a 3-5 hour POC this uses a persistent on-disk Chroma store with a small,
dependency-free hashing embedding function (see `_HashingEmbedding` below)
rather than Chroma's default, which downloads an ONNX model from the
internet on first use. For a handful of short, lexically distinct category
labels ("Course Conditions" vs. "Safety & Risk" vs. "Food & Beverage
Operations") this is plenty to retrieve the right standard, and it removes
a fragile runtime network dependency from container startup entirely -- a
deliberate reliability choice for a POC that needs to cold-start cleanly on
a HF Space. A production system would swap this for a real sentence-
embedding model and a managed vector store (see written summary, Next
Steps).
"""

from __future__ import annotations

import hashlib

import chromadb
import numpy as np
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.api import ClientAPI
from chromadb.config import Settings as ChromaSettings

from backend.config import settings

_COLLECTION_NAME = "brand_standards"

_client: ClientAPI | None = None


class _HashingEmbedding(EmbeddingFunction):
    """Deterministic, offline bag-of-words hashing embedding.

    Each token is hashed into one of `dim` buckets with a random sign
    (the classic "feature hashing" trick), then the vector is L2-normalized.
    No model download, no GPU, no external call -- just numpy.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vec = np.zeros(self.dim, dtype=np.float32)
            for token in text.lower().split():
                digest = hashlib.md5(token.encode("utf-8")).hexdigest()
                h = int(digest, 16)
                idx = h % self.dim
                sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
                vec[idx] += sign
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)
        return vectors


_embedding_fn = _HashingEmbedding()


def get_client() -> ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection():
    client = get_client()
    return client.get_or_create_collection(name=_COLLECTION_NAME, embedding_function=_embedding_fn)


def add_standards(brand: str, docs: list[dict[str, str]]) -> None:
    """
    docs: list of {"category": ..., "text": ...}
    Each doc becomes one embedded chunk, tagged with brand + category
    metadata so retrieval can filter precisely.
    """
    collection = get_collection()
    ids, texts, metadatas = [], [], []
    for i, d in enumerate(docs):
        doc_id = f"{brand}::{d['category']}::{i}"
        ids.append(doc_id)
        texts.append(d["text"])
        metadatas.append({"brand": brand, "category": d["category"]})
    # upsert keeps this idempotent across repeated seeding runs
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)


def retrieve_standards(brand: str, category: str, k: int = 3) -> list[str]:
    """Return up to k standard-text snippets relevant to this brand+category.

    Retrieval strategy: try an exact (brand, category) metadata match first
    -- this is the common, reliable case, since checklist categories in this
    POC are authored to match the seeded standards categories 1:1. If
    nothing matches exactly (e.g. an ad-hoc checklist item whose category
    label doesn't line up with the standards doc), fall back to an
    embedding-similarity search across the brand's standards as a
    best-effort attempt, using the lightweight hashing embedding described
    above -- a real semantic model would make this fallback meaningfully
    stronger (see Next Steps).
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    exact = collection.get(where={"$and": [{"brand": brand}, {"category": category}]}, limit=k)
    docs = exact.get("documents") or []
    if docs:
        return docs[:k]

    result = collection.query(query_texts=[category], n_results=k, where={"brand": brand})
    fallback_docs = result.get("documents", [[]])
    return fallback_docs[0] if fallback_docs else []
