/* Organisation configuration and read-only oversight workspace. */
(() => {
  const esc = escapeHtml;
  const roles = [
    ["lecturer_department_ids", "Lecturer"],
    ["programme_lead_department_ids", "Programme Lead"],
    ["curriculum_team_lead_department_ids", "Curriculum Team Lead"],
    ["iv_course_ids", "Coordinator (IV)"],
  ];
  function yearNow() {
    const now = new Date();
    const start = now.getMonth() >= 8 ? now.getFullYear() : now.getFullYear() - 1;
    return start + "/" + String((start + 1) % 100).padStart(2, "0");
  }
  let year = yearNow();
  const options = (items, chosen) => items.map(item => '<option value="' + esc(item.id) + '"' + (item.id === chosen ? ' selected' : '') + '>' + esc(item.title || item.name) + '</option>').join("");
  const checks = (items, name, chosen, unavailable = []) => items.map(item =>
    '<label class="tick-row"><input type="checkbox" name="' + name + '" value="' + esc(item.id) + '"' +
    (chosen.includes(item.id) ? ' checked' : '') + (unavailable.includes(item.id) ? ' disabled' : '') +
    '> <span>' + esc(item.title) + (unavailable.includes(item.id) ? ' (already allocated)' : '') + '</span></label>').join("") || '<p class="quiet">No entries configured yet.</p>';
  const formButton = '<button class="button-primary" type="submit">Save</button>';
  function heading(title, description) {
    return '<section class="page-heading"><div><div class="eyebrow">STAFF WORKSPACE</div><h1>' + esc(title) + '</h1><p>' + esc(description) + '</p></div></section>';
  }
  async function renderConfiguration() {
    if (!state.bootstrap.can_manage_organisation) return;
    const identity = state.identity;
    const requestedYear = year;
    const data = await api("/api/organisation?academic_year=" + encodeURIComponent(requestedYear));
    if (state.page !== "organisation" || state.identity !== identity || requestedYear !== year) return;
    const root = $("app");
    root.innerHTML = heading("Organisation", "Configure annual course ownership and staff responsibilities for approved accounts.") +
      '<section class="report-panel"><label>Academic year<input id="orgYear" value="' + esc(year) + '" pattern="20[0-9]{2}/[0-9]{2}" maxlength="7"></label><button id="orgYearLoad" type="button" class="button-ghost">Load year</button></section>' +
      '<section class="report-panel"><h2>Catalogue</h2><div class="report-grid">' +
      [["faculties", "Faculty"], ["departments", "Department"], ["courses", "Course"]].map(([key, label]) =>
        '<form class="feedback-form" data-catalogue="' + key + '"><h3>Add ' + label.toLowerCase() + '</h3><label>Code<input name="id" required maxlength="40" pattern="[a-zA-Z0-9_-]+"></label><label>Name<input name="title" required maxlength="120"></label>' +
        (key === "departments" ? '<label>Faculty<select name="faculty_id" required><option value="">Choose faculty</option>' + options(data.faculties) + '</select></label>' : '') +
        formButton + '</form>').join("") + '</div></section>' +
      '<section class="report-panel"><h2>Course departments</h2><label>Course<select id="orgCourse"><option value="">Choose course</option>' + options(data.courses) + '</select></label><div id="orgCourseForm"></div></section>' +
      '<section class="report-panel"><h2>Staff responsibilities</h2><p class="quiet">Only existing approved lecturer accounts can be allocated. Department access is read-only outside a lecturer’s own teaching allocations.</p><label>Lecturer<select id="orgStaff"><option value="">Choose lecturer</option>' + options(data.staff) + '</select></label><div id="orgStaffForm"></div></section>';
    const stillHere = () => state.identity === identity && state.page === "organisation";
    async function submit(path, method, payload, form) {
      const controls = [...root.querySelectorAll("button, input, select")].filter(control => !control.disabled);
      controls.forEach(control => { control.disabled = true; });
      try {
        await api(path, { method, body: JSON.stringify(payload) });
        if (stillHere()) { await renderConfiguration(); notify("Configuration saved"); }
      } catch (error) {
        if (stillHere()) notify(error.message);
      } finally { controls.forEach(control => { control.disabled = false; }); }
    }
    $("orgYearLoad").addEventListener("click", async () => {
      const candidate = $("orgYear").value.trim();
      if (!/^20\d\d\/\d\d$/.test(candidate) || (Number(candidate.slice(0,4)) + 1) % 100 !== Number(candidate.slice(-2))) return notify("Use an academic year such as 2026/27.");
      year = candidate;
      const controls = [...root.querySelectorAll("button, input, select")].filter(control => !control.disabled);
      controls.forEach(control => { control.disabled = true; });
      try { await renderConfiguration(); }
      catch (error) { if (stillHere()) notify(error.message); }
      finally { controls.forEach(control => { control.disabled = false; }); }
    });
    root.querySelectorAll("[data-catalogue]").forEach(form => form.addEventListener("submit", event => {
      event.preventDefault();
      return submit("/api/organisation/" + form.dataset.catalogue, "POST", Object.fromEntries(new FormData(form)), form);
    }));
    $("orgCourse").addEventListener("change", () => {
      const selected = data.courses.find(c => c.id === $("orgCourse").value);
      $("orgCourseForm").innerHTML = selected ? '<form class="feedback-form" id="courseDepartmentForm"><fieldset><legend>Associated departments</legend>' +
        checks(data.departments, "department_ids", selected.department_ids) + '</fieldset>' + formButton + '</form>' : "";
      $("courseDepartmentForm")?.addEventListener("submit", event => {
        event.preventDefault();
        const form = event.currentTarget;
        return submit("/api/organisation/courses/" + encodeURIComponent(selected.id) + "/departments/" + year, "PUT",
          { department_ids: new FormData(form).getAll("department_ids") }, form);
      });
    });
    $("orgStaff").addEventListener("change", () => {
      const selected = data.staff.find(u => u.id === $("orgStaff").value);
      const unavailable = data.courses.filter(c => c.coordinator_id && c.coordinator_id !== selected?.id).map(c => c.id);
      $("orgStaffForm").innerHTML = selected ? '<form class="feedback-form" id="staffAllocationForm">' +
        roles.map(([key, label]) => '<fieldset><legend>' + label + '</legend>' +
          checks(key === "iv_course_ids" ? data.courses : data.departments, key, selected[key], key === "iv_course_ids" ? unavailable : []) + '</fieldset>').join("") +
        formButton + '</form>' : "";
      $("staffAllocationForm")?.addEventListener("submit", event => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = new FormData(form);
        return submit("/api/organisation/staff/" + encodeURIComponent(selected.id) + "/allocations/" + year, "PUT",
          Object.fromEntries(roles.map(([key]) => [key, fields.getAll(key)])), form);
      });
    });
  }
  async function renderOversight() {
    if (!state.bootstrap.can_view_oversight) return;
    const identity = state.identity;
    const data = await api("/api/oversight");
    if (state.page !== "oversight" || state.identity !== identity) return;
    $("app").innerHTML = heading("Feedback oversight", "Read-only access to your authorised departments and IV courses, or all courses for Quality.") +
      '<section class="report-panel"><label>Class<select id="oversightCohort"><option value="">All authorised classes</option>' +
      options(data.cohorts.map(c => ({id:c.id, title:c.course + " · " + c.name + " · " + c.academic_year}))) +
      '</select></label><label>Learner<select id="oversightLearner"><option value="">All learners</option></select></label><div id="oversightResults"></div></section>';
    const cohort = $("oversightCohort"), learner = $("oversightLearner");
    function updateLearners() {
      const students = data.learners.filter(u => !cohort.value || u.cohort_id === cohort.value);
      learner.innerHTML = '<option value="">All learners</option>' + options(students.filter((u,i,a) => a.findIndex(v => v.id === u.id) === i));
    }
    function updateResults() {
      const rows = data.feedback.filter(t => (!cohort.value || t.cohort_id === cohort.value) && (!learner.value || t.learner_id === learner.value));
      const memberships = data.learners.filter(u => (!cohort.value || u.cohort_id === cohort.value) && (!learner.value || u.id === learner.value));
      $("oversightResults").innerHTML = '<p class="quiet">' + new Set(memberships.map(u => u.id)).size + ' learners · ' + rows.length + ' feedback records</p>' +
        (rows.length ? '<div class="information-list">' + rows.map(t => '<article class="feedback-card"><div class="cohort-byline">' + esc(t.cohort_name) + '</div><h3>' + esc(t.assignment) + '</h3><p>' + esc(t.learner) + ' · ' + esc(t.tutor) + '</p><p>' + esc(t.feedback_text) + '</p><span class="tag tag-neutral">' + esc(labelFor(t.status)) + '</span><button type="button" class="text-button" data-oversight-open="' + t.id + '">View feedback →</button></article>').join("") + '</div>' : '<p>No feedback in this selection.</p>');
    }
    cohort.addEventListener("change", () => { updateLearners(); updateResults(); });
    learner.addEventListener("change", updateResults);
    updateLearners();
    updateResults();
    $("oversightResults").addEventListener("click", async event => {
      const button = event.target.closest("[data-oversight-open]");
      if (!button) return;
      try {
        const t = await api("/api/oversight/feedback/" + button.dataset.oversightOpen);
        if (state.identity !== identity || state.page !== "oversight") return;
        $("detailTitle").textContent = t.assignment;
        $("threadDetail").innerHTML = '<div class="detail-section"><p class="tag tag-neutral">Read only · ' + esc(t.learner) + ' · ' + esc(t.tutor) + '</p><h3>Teacher feedback</h3><p>' + esc(t.feedback_text) + '</p>' +
          (t.judgement ? '<p>Judgement: ' + esc(t.judgement.replace(/_/g, " ")) + '</p>' : '') +
          (t.next_step ? '<h3>Next step</h3><p>' + esc(t.next_step) + '</p>' : '') +
          '<h3>Conversation and progress history</h3>' + t.timeline.map(e => '<p><strong>' + esc(e.actor) + '</strong> · ' + esc(niceDate(e.at)) + '<br>' + esc(e.text) + '</p>').join("") + '</div>';
        $("threadDialog").showModal();
      } catch (error) { notify(error.message); }
    });
  }
  window.organisation = { renderConfiguration, renderOversight };
})();
