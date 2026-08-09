"use strict";


/* ============================================================
   APPLICATION STATE
============================================================ */

const state = {
    stage: "intake",

    auditId: null,

    clarification: null,

    clarificationAnswers: {},

    report: null,

    locations: [],

    health: null
};


/* ============================================================
   CHECKLIST
============================================================ */

const CHECKLIST_TEMPLATE = [
    {
        category: "Course Conditions",
        questions: [
            "Greens are mowed/rolled with no visible scalping",
            "Bunkers have even, adequately raked sand with no standing water",
            "Cart paths are free of major cracks or potholes"
        ]
    },

    {
        category: "Clubhouse & Facility Cleanliness",
        questions: [
            "Restrooms are stocked and visibly clean",
            "Locker rooms are free of trash / standing water / odor",
            "Pro shop and common areas are clean and clutter-free"
        ]
    },

    {
        category: "Safety & Risk",
        questions: [
            "Lightning protocol signage is posted and staff can explain it",
            "Hazard areas are clearly marked",
            "Golf carts passed today's safety check"
        ]
    },

    {
        category: "Guest Service & Staff Standards",
        questions: [
            "Pace of play is being actively managed",
            "Staff are in uniform and greeted guests promptly"
        ]
    },

    {
        category: "Brand & Signage Compliance",
        questions: [
            "Exterior/interior signage uses the current brand template"
        ]
    },

    {
        category: "Food & Beverage Operations",
        questions: [
            "Food holding temps and date-labeling meet standard",
            "Menu pricing / offerings match the approved brand menu"
        ]
    }
];


const SEVERITY_COLORS = {
    critical: "#8B0000",
    high: "#D9534F",
    medium: "#E0A800",
    low: "#5B8C5A"
};


/* ============================================================
   DOM HELPERS
============================================================ */

const $ = (id) => document.getElementById(id);


function escapeHtml(value) {

    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


/* ============================================================
   API
============================================================ */

async function api(method, path, options = {}) {

    const response = await fetch(path, {
        method,

        headers: {
            "Content-Type": "application/json",

            ...(options.headers || {})
        },

        body: options.body
            ? JSON.stringify(options.body)
            : undefined
    });


    let data;

    try {
        data = await response.json();
    }

    catch {
        data = await response.text();
    }


    if (!response.ok) {

        let detail = data;

        if (data && typeof data === "object") {
            detail = data.detail || JSON.stringify(data);
        }

        throw new Error(`${response.status}: ${detail}`);
    }


    return data;
}


/* ============================================================
   UI
============================================================ */

function showLoading(message) {

    $("loadingMessage").textContent = message;

    $("loadingOverlay").classList.remove("hidden");
}


function hideLoading() {

    $("loadingOverlay").classList.add("hidden");
}


function showAlert(message, type = "error") {

    const alert = $("globalAlert");

    alert.textContent = message;

    alert.className = `alert ${type}`;

    alert.classList.remove("hidden");

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


function hideAlert() {

    $("globalAlert").classList.add("hidden");
}


function showStage(stage) {

    const stages = [
        "intake",
        "clarifying",
        "ready",
        "report"
    ];

    stages.forEach(name => {

        const element = $(`${name}Stage`);

        if (!element) return;

        element.classList.toggle(
            "hidden",
            name !== stage
        );
    });


    state.stage = stage;

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


/* ============================================================
   CHECKLIST RENDERING
============================================================ */

function renderChecklist() {

    const container = $("checklistContainer");

    container.innerHTML = "";


    CHECKLIST_TEMPLATE.forEach((section, sectionIndex) => {

        const sectionElement =
            document.createElement("div");

        sectionElement.className =
            "checklist-section";


        const header =
            document.createElement("div");

        header.className =
            "checklist-header";


        header.innerHTML = `
            <div>
                <div class="checklist-title">
                    ${escapeHtml(section.category)}
                </div>

                <div class="checklist-count">
                    ${section.questions.length} items
                </div>
            </div>

            <span>⌄</span>
        `;


        const body =
            document.createElement("div");

        body.className =
            "checklist-body";


        section.questions.forEach(
            (question, questionIndex) => {

                const item =
                    document.createElement("div");

                item.className =
                    "checklist-item";


                const questionId =
                    `q-${sectionIndex}-${questionIndex}`;


                item.innerHTML = `

                    <div class="question">
                        ${escapeHtml(question)}
                    </div>

                    <div class="response-options">

                        <label>
                            <input
                                type="radio"
                                name="${questionId}"
                                value="pass"
                            >

                            <span>Pass</span>
                        </label>

                        <label>
                            <input
                                type="radio"
                                name="${questionId}"
                                value="fail"
                            >

                            <span>Fail</span>
                        </label>

                        <label>
                            <input
                                type="radio"
                                name="${questionId}"
                                value="na"
                            >

                            <span>N/A</span>
                        </label>

                    </div>

                    <div
                        class="note-container hidden"
                        id="note-${questionId}"
                    >

                        <textarea
                            placeholder="What specifically did you observe? (where, how bad, vs. standard)"
                        ></textarea>

                    </div>
                `;


                body.appendChild(item);


                const radios =
                    item.querySelectorAll(
                        `input[name="${questionId}"]`
                    );


                radios.forEach(radio => {

                    radio.addEventListener(
                        "change",
                        () => {

                            const note =
                                $(`note-${questionId}`);

                            if (radio.value === "fail") {

                                note.classList.remove(
                                    "hidden"
                                );

                            } else {

                                note.classList.add(
                                    "hidden"
                                );

                                note
                                    .querySelector("textarea")
                                    .value = "";
                            }
                        }
                    );
                });
            }
        );


        sectionElement.appendChild(header);

        sectionElement.appendChild(body);


        header.addEventListener(
            "click",
            () => {

                body.classList.toggle("hidden");
            }
        );


        container.appendChild(sectionElement);
    });
}


/* ============================================================
   COLLECT CHECKLIST
============================================================ */

function collectChecklist() {

    const payload = [];


    CHECKLIST_TEMPLATE.forEach(
        (section, sectionIndex) => {

            section.questions.forEach(
                (question, questionIndex) => {

                    const questionId =
                        `q-${sectionIndex}-${questionIndex}`;


                    const selected =
                        document.querySelector(
                            `input[name="${questionId}"]:checked`
                        );


                    const noteElement =
                        $(`note-${questionId}`);


                    const note =
                        noteElement
                            ? noteElement
                                .querySelector("textarea")
                                .value
                                .trim()
                            : "";


                    payload.push({

                        category:
                            section.category,

                        question,

                        response:
                            selected
                                ? selected.value
                                : "na",

                        notes:
                            note
                    });
                }
            );
        }
    );


    return payload;
}


/* ============================================================
   LOCATION
============================================================ */

async function loadLocations() {

    const locations =
        await api("GET", "/locations");


    state.locations = locations;


    const select =
        $("locationSelect");


    select.innerHTML = "";


    locations.forEach(location => {

        const option =
            document.createElement("option");


        option.value =
            location.id;


        option.textContent =
            `${location.name} — ${location.address}`;


        select.appendChild(option);
    });


    if (!locations.length) {

        throw new Error(
            "No locations seeded yet."
        );
    }
}


/* ============================================================
   HEALTH
============================================================ */

async function loadHealth() {

    const health =
        await api("GET", "/health");


    state.health = health;


    const status =
        $("connectionStatus");


    status.textContent =
        "Backend connected";


    status.className =
        "status-pill connected";


    $("reviewMode").textContent =
        health.reviews_are_mocked
            ? "Mock / demo"
            : "Live Google Places";


    if (!health.llm_configured) {

        showAlert(
            "GROQ_API_KEY is not configured. The AI pipeline cannot run until the API key is added as an environment secret.",
            "error"
        );
    }
}


/* ============================================================
   PRE-CHECK
============================================================ */

async function runPreCheck(event) {

    event.preventDefault();


    hideAlert();


    const locationId =
        Number($("locationSelect").value);


    const consultantName =
        $("consultantName")
            .value
            .trim();


    if (!locationId) {

        showAlert(
            "Please select a location."
        );

        return;
    }


    if (!consultantName) {

        showAlert(
            "Please enter the consultant name."
        );

        return;
    }


    const payload = {

        location_id:
            locationId,

        consultant_name:
            consultantName,

        checklist:
            collectChecklist(),

        free_text_notes:
            $("freeTextNotes")
                .value
                .trim(),

        photo_description:
            $("photoDescription")
                .value
                .trim()
    };


    try {

        showLoading(
            "Checking whether the input is specific enough..."
        );


        const result =
            await api(
                "POST",
                "/audits/clarify",
                {
                    body: payload
                }
            );


        state.auditId =
            result.audit_id;


        state.clarification =
            result.clarification;


        const clarification =
            result.clarification;


        if (
            !clarification.is_sufficient &&
            clarification.clarifying_questions &&
            clarification.clarifying_questions.length
        ) {

            renderClarification(
                clarification
            );

            showStage("clarifying");

        }

        else {

            showStage("ready");
        }

    }

    catch (error) {

        showAlert(
            `Pre-check failed: ${error.message}`
        );

    }

    finally {

        hideLoading();
    }
}


/* ============================================================
   CLARIFICATION
============================================================ */

function renderClarification(clarification) {

    $("clarificationReasoning")
        .textContent =
        clarification.reasoning || "";


    const container =
        $("clarificationQuestions");


    container.innerHTML = "";


    state.clarificationAnswers = {};


    clarification
        .clarifying_questions
        .forEach((question, index) => {

            const wrapper =
                document.createElement("div");


            wrapper.className =
                "clarification-question";


            wrapper.innerHTML = `

                <label for="clarification-${index}">
                    ${escapeHtml(question)}
                </label>

                <textarea
                    id="clarification-${index}"
                    rows="3"
                    data-question="${escapeHtml(question)}"
                    placeholder="Add the specific details you observed..."
                ></textarea>

            `;


            container.appendChild(wrapper);
        });
}


/* ============================================================
   RUN AUDIT
============================================================ */

async function runAudit(proceedAnyway) {

    hideAlert();


    const answers = [];


    document
        .querySelectorAll(
            "#clarificationQuestions textarea"
        )
        .forEach(textarea => {

            const answer =
                textarea.value.trim();


            if (answer) {

                answers.push({

                    question:
                        textarea.dataset.question,

                    answer
                });
            }
        });


    const locationId =
        Number($("locationSelect").value);


    const consultantName =
        $("consultantName")
            .value
            .trim();


    try {

        showLoading(
            "Generating findings, pulling recent reviews, and drafting the corrective plan..."
        );


        const report =
            await api(
                "POST",
                "/audits/run",
                {
                    body: {

                        location_id:
                            locationId,

                        consultant_name:
                            consultantName,

                        checklist: [],

                        audit_id:
                            state.auditId,

                        clarification_answers:
                            answers,

                        proceed_despite_gaps:
                            proceedAnyway
                    }
                }
            );


        state.report =
            report;


        renderReport(report);


        showStage("report");

    }

    catch (error) {

        showAlert(
            `Report generation failed: ${error.message}`
        );

    }

    finally {

        hideLoading();
    }
}


/* ============================================================
   REPORT
============================================================ */

function renderReport(report) {

    $("reportTitle").textContent =
        `Audit Report · ${report.location.name}`;


    $("overallSummary").textContent =
        report.overall_summary || "";


    const findings =
        report.findings || [];


    $("findingCount").textContent =
        findings.length;


    renderFindings(findings);

    renderReviewInsights(
        report.review_insights
    );


    $("franchiseeMessage").textContent =
        report.franchisee_message || "";


    renderCorrectiveActions(
        report.corrective_actions || []
    );


    if (
        report.review_insights &&
        report.review_insights.themes &&
        report.review_insights.themes.length
    ) {

        renderFranchiseeReviews(
            report.review_insights
        );

    }


    const warning =
        $("mockReviewsWarning");


    if (report.reviews_are_mocked) {

        warning.classList.remove("hidden");

    }

    else {

        warning.classList.add("hidden");
    }


    loadAuditTrail(
        report.audit_id
    );
}


/* ============================================================
   FINDINGS
============================================================ */

function renderFindings(findings) {

    const container =
        $("findingsContainer");


    container.innerHTML = "";


    if (!findings.length) {

        container.innerHTML = `

            <div class="info-card">

                No compliance issues identified
                this visit.

            </div>
        `;

        return;
    }


    findings.forEach(finding => {

        const severity =
            finding.severity || "low";


        const color =
            SEVERITY_COLORS[severity] ||
            "#888";


        const confidence =
            Math.round(
                (finding.confidence || 0) * 100
            );


        const reviewBadge =
            finding.requires_human_review
                ? `
                    <span class="badge review-badge">
                        NEEDS HUMAN REVIEW
                    </span>
                  `
                : "";


        const standard =
            finding.standard_reference
                ? `
                    <div>
                        <strong>Standard:</strong>
                        ${escapeHtml(
                            finding.standard_reference
                        )}
                    </div>
                  `
                : "";


        const element =
            document.createElement("div");


        element.className =
            "finding-card";


        element.innerHTML = `

            <div class="finding-header">

                <span
                    class="badge"
                    style="background:${color}"
                >
                    ${escapeHtml(
                        severity.toUpperCase()
                    )}
                </span>

                ${reviewBadge}

                <span class="finding-category">
                    ${escapeHtml(
                        finding.category
                    )}
                </span>

                <span class="confidence">
                    · confidence: ${confidence}%
                </span>

            </div>


            <div class="finding-summary">

                ${escapeHtml(
                    finding.finding_summary
                )}

            </div>


            <div class="evidence">

                <div>
                    <strong>Evidence:</strong>
                    ${escapeHtml(
                        finding.supporting_evidence
                    )}
                </div>

                ${standard}

            </div>
        `;


        container.appendChild(element);
    });
}


/* ============================================================
   PUBLIC REVIEWS
============================================================ */

function renderReviewInsights(insights) {

    const section =
        $("reviewInsightsSection");


    if (
        !insights ||
        !insights.themes ||
        !insights.themes.length
    ) {

        section.classList.add("hidden");

        return;
    }


    section.classList.remove("hidden");


    $("reviewCaveat").textContent =
        insights.caveat || "";


    const container =
        $("reviewThemes");


    container.innerHTML = "";


    insights.themes.forEach(theme => {

        const confidence =
            theme.linkage_confidence || "low";


        const colors = {

            low: "#999",

            medium: "#E0A800",

            high: "#D9534F"
        };


        const element =
            document.createElement("div");


        element.className =
            "review-theme";


        element.innerHTML = `

            <div class="review-theme-header">

                <strong>
                    ${escapeHtml(
                        theme.theme
                    )}
                </strong>

                <span
                    class="link-badge"
                    style="
                        background:${colors[confidence]};
                        color:white;
                    "
                >
                    link: ${escapeHtml(
                        confidence
                    )}
                </span>

                <span class="confidence">
                    ${theme.mention_count}
                    mentions
                </span>

            </div>


            <div>
                ${escapeHtml(
                    theme.linkage_note
                )}
            </div>


            ${
                theme.linked_categories &&
                theme.linked_categories.length
                    ? `
                        <div
                            class="confidence"
                            style="margin-top:8px"
                        >
                            Related categories:
                            ${theme.linked_categories
                                .map(escapeHtml)
                                .join(", ")}
                        </div>
                      `
                    : ""
            }

        `;


        container.appendChild(element);
    });
}


/* ============================================================
   FRANCHISEE VIEW
============================================================ */

function renderCorrectiveActions(actions) {

    const container =
        $("correctiveActionsContainer");


    const section =
        $("correctiveActionsSection");


    if (!actions.length) {

        container.innerHTML = `

            <div class="info-card">

                No corrective actions needed this visit —
                nice work.

            </div>
        `;

        return;
    }


    let html = `

        <table>

            <thead>

                <tr>
                    <th>Action</th>
                    <th>Owner</th>
                    <th>Suggested deadline</th>
                </tr>

            </thead>

            <tbody>
    `;


    actions.forEach(action => {

        html += `

            <tr>

                <td>
                    ${escapeHtml(
                        action.action_text
                    )}
                </td>

                <td>
                    ${escapeHtml(
                        action.owner
                    )}
                </td>

                <td>
                    ${escapeHtml(
                        action.suggested_deadline_days
                    )}
                    days
                </td>

            </tr>
        `;
    });


    html += `
            </tbody>

        </table>
    `;


    container.innerHTML =
        html;


    section.classList.remove("hidden");
}


function renderFranchiseeReviews(insights) {

    const section =
        $("franchiseeReviewsSection");


    section.classList.remove("hidden");


    $("franchiseeReviewCaveat")
        .textContent =
        insights.caveat || "";


    const container =
        $("franchiseeReviewThemes");


    container.innerHTML = "";


    insights.themes.forEach(theme => {

        const element =
            document.createElement("div");


        element.className =
            "review-theme";


        element.innerHTML = `

            <strong>
                ${escapeHtml(
                    theme.theme
                )}
            </strong>

            <div style="margin-top:6px">
                ${escapeHtml(
                    theme.linkage_note
                )}
            </div>

        `;


        container.appendChild(element);
    });
}


/* ============================================================
   AUDIT TRAIL
============================================================ */

async function loadAuditTrail(auditId) {

    const container =
        $("auditTrailContainer");


    container.innerHTML =
        "Loading audit trail...";


    try {

        const trail =
            await api(
                "GET",
                `/audits/${auditId}/trail`
            );


        if (!trail.length) {

            container.innerHTML =
                "No audit trail entries available.";

            return;
        }


        container.innerHTML = "";


        trail.forEach(entry => {

            const element =
                document.createElement("div");


            element.className =
                "trail-entry";


            element.innerHTML = `

                <div class="trail-header">

                    ${escapeHtml(
                        entry.step_name
                    )}

                    ·

                    <code>
                        ${escapeHtml(
                            entry.model_used
                        )}
                    </code>

                    ·

                    ${escapeHtml(
                        entry.created_at
                    )}

                </div>


                <div>
                    <strong>Prompt</strong>
                </div>

                <pre class="trail-code">${escapeHtml(
                    entry.prompt
                )}</pre>


                <div>
                    <strong>Response</strong>
                </div>

                <pre class="trail-code">${escapeHtml(
                    entry.response
                )}</pre>

            `;


            container.appendChild(element);
        });

    }

    catch (error) {

        container.innerHTML = "";

        showAlert(
            `Could not load audit trail: ${error.message}`
        );
    }
}


/* ============================================================
   RESET
============================================================ */

function resetAudit() {

    state.stage =
        "intake";

    state.auditId =
        null;

    state.clarification =
        null;

    state.clarificationAnswers =
        {};

    state.report =
        null;


    $("auditForm").reset();


    $("consultantName").value =
        "Jordan Rivera";


    $("proceedAnyway").checked =
        false;


    renderChecklist();


    hideAlert();


    showStage("intake");
}


/* ============================================================
   TABS
============================================================ */

function setupTabs() {

    document
        .querySelectorAll(".tab-button")
        .forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    const tab =
                        button.dataset.tab;


                    document
                        .querySelectorAll(".tab-button")
                        .forEach(btn =>
                            btn.classList.remove(
                                "active"
                            )
                        );


                    document
                        .querySelectorAll(".tab-content")
                        .forEach(content =>
                            content.classList.remove(
                                "active"
                            )
                        );


                    button.classList.add(
                        "active"
                    );


                    $(`${tab}Tab`)
                        .classList.add(
                            "active"
                        );
                }
            );
        });
}


/* ============================================================
   EVENTS
============================================================ */

function setupEvents() {

    $("auditForm")
        .addEventListener(
            "submit",
            runPreCheck
        );


    $("submitClarificationBtn")
        .addEventListener(
            "click",
            () => runAudit(
                $("proceedAnyway").checked
            )
        );


    $("clarificationResetBtn")
        .addEventListener(
            "click",
            resetAudit
        );


    $("generateReportBtn")
        .addEventListener(
            "click",
            () => runAudit(false)
        );


    $("backToChecklistBtn")
        .addEventListener(
            "click",
            () => showStage("intake")
        );


    $("resetSessionBtn")
        .addEventListener(
            "click",
            resetAudit
        );


    $("newAuditBtn")
        .addEventListener(
            "click",
            resetAudit
        );
}


/* ============================================================
   INITIALIZATION
============================================================ */

async function initialize() {

    $("backendUrl").textContent =
        window.location.origin;


    renderChecklist();

    setupEvents();

    setupTabs();


    try {

        await loadHealth();

        await loadLocations();

    }

    catch (error) {

        $("connectionStatus").textContent =
            "Backend unavailable";


        $("connectionStatus").className =
            "status-pill error";


        showAlert(
            `Cannot connect to backend: ${error.message}`
        );
    }
}


document.addEventListener(
    "DOMContentLoaded",
    initialize
);