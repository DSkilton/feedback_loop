/* Feedback Loop: synthetic-data-only UI. Never use demo identity switching in production. */
const people = [
  { id: "tutor-1", label: "Jo Morgan · Tutor" },
  { id: "learner-1", label: "Alex Taylor · Learner" },
  { id: "learner-2", label: "Morgan Ellis · Learner" },
  { id: "admin-1", label: "Quality Team · Administrator" },
];
const columns = [
  { key: "ACTION_REQUIRED", name: "Action required", hint: "Start here", tone: "amber" },
  { key: "IN_PROGRESS", name: "In progress", hint: "Working on it", tone: "blue" },
  { key: "READY_FOR_REVIEW", name: "Ready for review", hint: "Tutor to check", tone: "violet" },
  { key: "CLOSED", name: "Completed", hint: "Closed by tutor", tone: "green" },
];
const state = { identity: "tutor-1", bootstrap: null, threads: [], page: "board", learnerFilter: "all", selected: null };
const $ = (id) => document.getElementById(id);
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function niceDate(value) {
  if (!value) return "Not yet";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "Not available" : new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(d);
}
function labelFor(status) {
  return columns.find((c) => c.key === status)?.name || (status === "INFORMATION" ? "For information" : status);
}
function notify(text) {
  const toast = $("toast");
  toast.textContent = text;
  toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.classList.remove("show"), 3500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-Demo-User": state.identity, ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(typeof problem.detail === "string" ? problem.detail : "Request failed");
  }
  return response.json();
}
async function refresh() {
  try {
    state.bootstrap = await api("/api/bootstrap");
    state.threads = state.bootstrap.user.role === "admin" ? [] : await api("/api/threads");
    state.page = state.bootstrap.user.role === "admin" ? "reports" : "board";
    updateNavigation();
    await render();
  } catch (err) {
    $("app").innerHTML = '<div class="error-panel"><h2>Unable to load the demonstration</h2><p>' + escapeHtml(err.message) + '</p><p>Start the app with <code>FEEDBACK_LOOP_DEMO_MODE=1</code>. This demonstration must run only on localhost.</p></div>';
  }
}
function updateNavigation() {
  const admin = state.bootstrap?.user.role === "admin";
  $("reportsNav").hidden = !admin;
  $("boardNav").hidden = admin;
  document.querySelectorAll("[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === state.page));
}
function filterThreads() {
  return state.learnerFilter === "all" ? state.threads : state.threads.filter((item) => item.learner_id === state.learnerFilter);
}
function card(thread) {
  const isTeacher = state.bootstrap.user.role === "tutor";
  const type = thread.feedback_required ? "Feedback required" : "For information";
  return '<article class="feedback-card" tabindex="0" aria-label="' + escapeHtml(thread.assignment) + ' feedback for ' + escapeHtml(thread.learner) + '">' +
    '<div class="card-top"><span class="module-label">' + escapeHtml(thread.module) + '</span><span class="card-date">' + niceDate(thread.updated_at) + '</span></div>' +
    '<h3>' + escapeHtml(thread.assignment) + '</h3>' +
    (isTeacher ? '<div class="learner-byline">↳ ' + escapeHtml(thread.learner) + '</div>' : '') +
    (thread.criterion ? '<div class="criterion">' + escapeHtml(thread.criterion) + '</div>' : '') +
    '<p class="feedback-excerpt">' + escapeHtml(thread.feedback_text) + '</p>' +
    (thread.next_step ? '<div class="next-step"><span class="step-label">NEXT STEP</span>' + escapeHtml(thread.next_step) + '</div>' : '') +
    '<div class="card-foot"><span class="tag ' + (thread.feedback_required ? "tag-action" : "tag-info") + '">' + type + '</span>' +
    '<button class="text-button" type="button" data-open="' + thread.id + '">Open →</button></div></article>';
}
function renderBoard() {
  const isTeacher = state.bootstrap.user.role === "tutor";
  const list = filterThreads();
  const fullName = state.bootstrap.user.name.split(" ")[0];
  const greeting = isTeacher ? "Support every next step." : "Your progress, one step at a time.";
  const headline = isTeacher ? "Learner improvement board" : "My feedback board";
  const required = list.filter((t) => t.feedback_required);
  const working = required.filter((t) => t.status === "IN_PROGRESS").length;
  const review = required.filter((t) => t.status === "READY_FOR_REVIEW").length;
  const done = required.filter((t) => t.status === "CLOSED").length;
  const roster = isTeacher
    ? '<label class="filter-label">Learner <select id="learnerFilter"><option value="all">All learners</option>' +
      state.bootstrap.learners.map((u) => '<option value="' + escapeHtml(u.id) + '"' + (u.id === state.learnerFilter ? " selected" : "") + '>' + escapeHtml(u.name) + '</option>').join("") + '</select></label>'
    : "";
  $("app").innerHTML =
    '<section class="page-heading"><div><div class="eyebrow">WELCOME BACK, ' + escapeHtml(fullName.toUpperCase()) + '</div><h1>' + headline + '</h1><p>' + greeting + '</p></div>' +
    (isTeacher ? '<button class="button-primary" id="createButton" type="button">＋ Share feedback</button>' : '<span class="pale-pill">Your private workspace</span>') + '</section>' +
    '<div class="intro-strip"><span class="intro-symbol">✦</span><p><strong>Feedback is a conversation.</strong> Read your tutor’s comments, take the next step, and submit your work for review. Only a tutor can close the loop.</p></div>' +
    '<section class="metrics" aria-label="Board overview"><div class="metric"><span>Actions on board</span><strong>' + required.length + '</strong></div><div class="metric"><span>In progress</span><strong>' + working + '</strong></div><div class="metric"><span>Awaiting tutor</span><strong>' + review + '</strong></div><div class="metric"><span>Completed</span><strong>' + done + '</strong></div></section>' +
    '<div class="board-controls"><div><h2>Feedback journey</h2><p>Move your work forward. Keep the discussion open.</p></div>' + roster + '</div>' +
    '<section class="kanban" aria-label="Feedback progress board">' + columns.map((column) => {
      const cards = list.filter((t) => t.status === column.key);
      return '<div class="board-column tone-' + column.tone + '"><div class="column-heading"><div class="column-title"><span class="column-dot"></span><h3>' + column.name + '</h3></div><span class="count">' + cards.length + '</span></div><div class="column-hint">' + column.hint + '</div><div class="card-stack">' +
        (cards.length ? cards.map(card).join("") : '<div class="empty-column">No feedback in this stage</div>') +
      '</div></div>';
    }).join("") + '</section>' +
    (list.some((t) => t.status === "INFORMATION") ?
      '<section class="information-section"><h2>Shared for information</h2><p>Feedback with no action currently required.</p><div class="information-list">' + list.filter((t) => t.status === "INFORMATION").map(card).join("") + '</div></section>' : '') +
    '<footer class="page-footer">Prototype for co-design. Initial assessment feedback is also recorded in Microsoft Teams.</footer>';
  if (isTeacher) $("createButton").addEventListener("click", openCreate);
  const select = $("learnerFilter");
  if (select) select.addEventListener("change", (event) => { state.learnerFilter = event.target.value; renderBoard(); });
}
async function renderReports() {
  const report = await api("/api/reports");
  const max = Math.max(1, ...report.by_status.map((s) => s.count));
  const focusMax = Math.max(1, ...report.focus_areas.map((s) => s.count));
  $("app").innerHTML =
    '<section class="page-heading"><div><div class="eyebrow">QUALITY ASSURANCE · SYNTHETIC DATA</div><h1>Learning progress overview</h1><p>Aggregate measures to support conversations and improvement, not automated judgements.</p></div><span class="pale-pill">Computing pilot</span></section>' +
    '<div class="report-alert"><strong>Demonstration report.</strong> All data is synthetic. This view contains no learner-level records or private pastoral notes.</div>' +
    '<section class="metrics admin-metrics" aria-label="Quality summary"><div class="metric"><span>Feedback records</span><strong>' + report.total + '</strong><small>All demonstration entries</small></div><div class="metric"><span>Actions identified</span><strong>' + report.actions_required + '</strong><small>Feedback required is ticked</small></div><div class="metric"><span>Pending tutor review</span><strong>' + report.awaiting_review + '</strong><small>Ready for review stage</small></div><div class="metric"><span>Closed by tutors</span><strong>' + report.closed + '</strong><small>Reviewed and completed</small></div></section>' +
    '<div class="report-grid"><section class="report-panel"><div class="panel-heading"><div><h2>Feedback pipeline</h2><p>Current distribution across workflow stages</p></div><span class="panel-chip">STATUS</span></div>' +
    '<div class="bar-list">' + report.by_status.map((item, i) =>
      '<div class="bar-row"><span>' + escapeHtml(labelFor(item.status)) + '</span><div class="bar-track"><div class="bar-fill fill-' + i + '" style="width:' + (item.count / max * 100) + '%"></div></div><strong>' + item.count + '</strong></div>'
    ).join("") + '</div></section>' +
    '<section class="report-panel"><div class="panel-heading"><div><h2>Development focus</h2><p>Topics manually tagged by tutors</p></div><span class="panel-chip">SKILLS</span></div>' +
    '<div class="bar-list">' + (report.focus_areas.length ? report.focus_areas.map((item) =>
      '<div class="bar-row"><span>' + escapeHtml(item.name) + '</span><div class="bar-track"><div class="bar-fill focus-fill" style="width:' + (item.count / focusMax * 100) + '%"></div></div><strong>' + item.count + '</strong></div>'
    ).join("") : '<p>No focus areas have been tagged yet.</p>') + '</div></section></div>' +
    '<section class="report-panel report-notes"><div class="panel-heading"><div><h2>Interpretation and next steps</h2><p>Quality reporting should prompt discussion, not replace professional judgement.</p></div></div><div class="principle-grid"><div><strong>01 · Review patterns</strong><p>Discuss repeated areas with tutors and consider appropriate teaching support.</p></div><div><strong>02 · Preserve context</strong><p>Numbers alone cannot explain a learner’s personal circumstances or development.</p></div><div><strong>03 · Protect privacy</strong><p>Do not include pastoral information in ordinary quality reports.</p></div></div></section>' +
    '<footer class="page-footer">' + escapeHtml(report.note) + '</footer>';
}
async function render() {
  if (state.page === "reports") await renderReports();
  else renderBoard();
}
function openCreate() {
  $("assignmentSelect").innerHTML = state.bootstrap.assignments.map((a) =>
    '<option value="' + escapeHtml(a.id) + '">' + escapeHtml(a.module + " · " + a.title) + '</option>').join("");
  $("learnerSelect").innerHTML = state.bootstrap.learners.map((u) =>
    '<option value="' + escapeHtml(u.id) + '">' + escapeHtml(u.name) + '</option>').join("");
  $("createError").textContent = "";
  $("newForm").reset();
  $("newDialog").showModal();
}
function actionButtons(thread) {
  const isLearner = state.bootstrap.user.role === "learner";
  const targetLabels = [];
  if (isLearner) {
    if (thread.status === "ACTION_REQUIRED") targetLabels.push(["IN_PROGRESS", "Start working"]);
    if (thread.status === "IN_PROGRESS") targetLabels.push(["READY_FOR_REVIEW", "Submit for tutor review"], ["ACTION_REQUIRED", "Move back"]);
    if (thread.status === "READY_FOR_REVIEW") targetLabels.push(["IN_PROGRESS", "Continue working"]);
  } else {
    if (thread.status === "READY_FOR_REVIEW") targetLabels.push(["CLOSED", "✓ Close feedback loop"], ["IN_PROGRESS", "Return for further work"]);
    if (thread.status === "INFORMATION") targetLabels.push(["CLOSED", "Mark as reviewed"]);
    if (thread.status === "CLOSED") targetLabels.push(["ACTION_REQUIRED", "Reopen feedback"]);
  }
  return targetLabels.map(([key, label]) => '<button type="button" class="' + (key === "CLOSED" ? "button-primary" : "button-ghost") +
    '" data-status="' + key + '" data-id="' + thread.id + '">' + escapeHtml(label) + '</button>').join("");
}
async function openThread(fid) {
  const t = await api("/api/threads/" + fid);
  state.selected = fid;
  $("detailTitle").textContent = t.assignment;
  $("threadDetail").innerHTML =
    '<div class="detail-overview"><div class="detail-tags"><span class="tag tag-action">' + escapeHtml(labelFor(t.status)) + '</span><span class="tag tag-neutral">' + escapeHtml(t.module) + '</span></div><div class="detail-meta">Learner · ' + escapeHtml(t.learner) +
    ' · Updated ' + niceDate(t.updated_at) + '</div><div class="detail-section"><h3>Teacher feedback</h3>' +
    (t.criterion ? '<div class="criterion">' + escapeHtml(t.criterion) + '</div>' : '') +
    '<p>' + escapeHtml(t.feedback_text) + '</p></div>' +
    (t.feedback_required ? '<div class="detail-next"><span class="step-label">YOUR NEXT STEP</span><p>' + escapeHtml(t.next_step) + '</p></div>' : '<div class="detail-next info"><strong>No action required.</strong> This feedback is shared for information.</div>') +
    '<div class="teams-reference"><strong>Initial feedback in Teams</strong><span>' + escapeHtml(t.teams_reference) + '</span><small>Reference entered manually by the tutor. Sync is not enabled.</small></div></div>' +
    (state.bootstrap.user.role === "learner" && t.status === "IN_PROGRESS" ?
      '<label class="progress-prompt" for="progressEvidence">What have you changed?<textarea id="progressEvidence" rows="3" maxlength="2000" placeholder="Describe the changes you made and how they address the feedback."></textarea><small>This explanation is saved to your conversation when you submit for review.</small></label>' : '') +
    '<div class="detail-actions">' + actionButtons(t) + '</div>' +
    '<div class="timeline"><h3>Conversation and progress history</h3>' +
    (t.timeline.length ? t.timeline.map((entry) =>
      '<div class="timeline-entry"><span class="timeline-marker ' + (entry.type === "comment" ? "marker-comment" : "") + '"></span><div><div class="timeline-meta"><strong>' + escapeHtml(entry.actor) + '</strong><span>' + niceDate(entry.at) + '</span></div><p>' + escapeHtml(entry.text).replace(/\n/g, "<br>") + '</p></div></div>'
    ).join("") : '<p class="quiet">No updates recorded yet.</p>') +
    '</div><form id="commentForm" class="comment-form"><label for="commentText">Add to the conversation</label><textarea name="commentText" id="commentText" rows="3" maxlength="2000" required placeholder="Explain progress, ask for support, or offer guidance."></textarea><button class="button-primary" type="submit">Post comment</button></form>';
  if (!$("threadDialog").open) $("threadDialog").showModal();
  $("commentForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/threads/" + fid + "/comments", { method: "POST", body: JSON.stringify({ body: $("commentText").value }) });
      await openThread(fid);
      notify("Comment added");
    } catch (e) { notify(e.message); }
  });
}
async function changeStatus(fid, status) {
  try {
    const progress_note = $("progressEvidence")?.value || "";
    await api("/api/threads/" + fid + "/status", { method: "POST", body: JSON.stringify({ status, progress_note }) });
    $("threadDialog").close();
    await refresh();
    notify("Progress updated");
  } catch (error) { notify(error.message); }
}
$("identitySelect").addEventListener("change", async (event) => {
  state.identity = event.target.value;
  state.learnerFilter = "all";
  $("threadDialog").close();
  $("newDialog").close();
  await refresh();
});
document.addEventListener("click", async (event) => {
  const close = event.target.closest("[data-close]");
  if (close) { $(close.dataset.close).close(); return; }
  const open = event.target.closest("[data-open]");
  if (open) { try { await openThread(open.dataset.open); } catch (e) { notify(e.message); } return; }
  const status = event.target.closest("[data-status]");
  if (status) { await changeStatus(status.dataset.id, status.dataset.status); return; }
});
$("newForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("createError").textContent = "";
  const form = new FormData(event.currentTarget);
  const data = Object.fromEntries(form.entries());
  data.feedback_required = $("newForm").elements.feedback_required.checked;
  try {
    await api("/api/threads", { method: "POST", body: JSON.stringify(data) });
    $("newDialog").close();
    await refresh();
    notify("Teacher feedback added to the board");
  } catch (error) { $("createError").textContent = error.message; }
});
refresh();
