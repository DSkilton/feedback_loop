class BulkFeedbackView {
  constructor() {
    this.context = "";
    this.rows = new Map();
    this.global = {};
    this.dirty = new Set();
    this.writeQueue = Promise.resolve();
    this.timer = null;
    this.submitting = false;
    this.justSaved = new Set();
    this.storageError = "";
    this.feedbackRequired = false;
  }

  scope() {
    return state.bootstrap?.user?.id || state.identity;
  }

  prefix() {
    return ["feedback-v1", this.scope(), this.cohortId, this.assignmentId].join("|") + "|";
  }

  key(learnerId) {
    return this.prefix() + learnerId;
  }

  assignments() {
    return state.bootstrap.assignments.filter((a) => a.cohort_id === this.cohortId);
  }

  learners() {
    return state.bootstrap.learners.filter((a) => a.cohort_id === this.cohortId)
      .filter((a, i, all) => all.findIndex((b) => b.id === a.id) === i);
  }

  async render() {
    if (state.bootstrap?.user?.role !== "tutor") return;
    const cohorts = state.bootstrap.cohorts;
    if (!cohorts.length) {
      $("app").innerHTML = '<section class="page-heading"><h1>Class feedback</h1><p>No teaching cohorts are assigned to your account.</p></section>';
      return;
    }
    if (!this.context || this.context.split("|")[0] !== this.scope()) {
      this.cohortId = cohorts[0].id;
      this.assignmentId = this.assignments()[0]?.id || "";
      await this.load();
    }
    this.paint();
  }

  async load() {
    this.rows = new Map();
    this.justSaved.clear();
    this.context = this.scope() + "|" + this.cohortId + "|" + this.assignmentId;
    this.global = { teams_reference: "", teams_recorded_confirmed: false, feedback_required: false, criterion_id: "" };
    try {
      const drafts = await window.feedbackDraftStore.list(this.prefix());
      for (const draft of drafts) {
        if (draft.key === this.prefix() + "__meta__") this.global = { ...this.global, ...draft.value };
        else this.rows.set(draft.learner_id, draft);
      }
      this.storageError = "";
    } catch (error) {
      this.storageError = error.message;
    }
  }

  getRow(learnerId) {
    if (!this.rows.has(learnerId)) {
      this.rows.set(learnerId, {
        key: this.key(learnerId), learner_id: learnerId, client_key: crypto.randomUUID(),
        feedback_text: "", next_step: "", judgement: "", work_url: "",
        submission: null, uncertain: false, error: "",
      });
    }
    return this.rows.get(learnerId);
  }

  setStatus(message) {
    const element = $("draftStatus");
    if (element) element.textContent = message;
  }

  scheduleSave(key) {
    this.dirty.add(key);
    this.setStatus("Saving locally…");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.flush().catch(() => {}); }, 250);
  }

  async flush() {
    clearTimeout(this.timer);
    this.timer = null;
    const keys = [...this.dirty];
    this.dirty.clear();
    if (!keys.length) return this.writeQueue;
    this.writeQueue = this.writeQueue.catch(() => {}).then(async () => {
      try {
        for (const key of keys) {
          const value = key === this.prefix() + "__meta__"
            ? { key, learner_id: "__meta__", value: { ...this.global } }
            : this.rows.get(key.slice(this.prefix().length));
          if (value) await window.feedbackDraftStore.put(value);
        }
        this.storageError = "";
        this.setStatus("Saved locally");
      } catch (error) {
        for (const key of keys) this.dirty.add(key);
        this.storageError = error.message;
        this.setStatus("Local save failed: " + error.message);
        throw error;
      }
    });
    return this.writeQueue;
  }

  async switchContext(cohort, assignment) {
    await this.flush();
    this.cohortId = cohort;
    this.assignmentId = assignment;
    await this.load();
    this.paint();
  }

  paint() {
    const cohorts = state.bootstrap.cohorts;
    const available = this.assignments();
    const html = escapeHtml;
    $("app").innerHTML =
      '<section class="page-heading"><div><div class="eyebrow">TUTOR · QUICK ENTRY</div><h1>Whole-class feedback</h1>' +
      '<p>Write feedback for your class, then publish populated rows with one click.</p></div></section>' +
      '<form id="bulkForm" class="bulk-form"><section class="bulk-settings">' +
      '<label>Cohort<select id="bulkCohort">' + cohorts.map((c) =>
        '<option value="' + html(c.id) + '"' + (c.id === this.cohortId ? " selected" : "") + '>' + html(c.name) + '</option>').join("") + '</select></label>' +
      '<label>Assignment<select id="bulkAssignment">' + available.map((a) =>
        '<option value="' + html(a.id) + '"' + (a.id === this.assignmentId ? " selected" : "") + '>' + html(a.module + " · " + a.title) + '</option>').join("") + '</select></label>' +
      '<label>Criterion<select data-global="criterion_id"><option value="">Not selected</option>' +
      state.bootstrap.criteria.filter((c) => c.assignment_id === this.assignmentId).map((c) =>
        '<option value="' + c.id + '"' + (String(c.id) === String(this.global.criterion_id) ? " selected" : "") + '>' + html(c.code + " · " + c.description) + '</option>').join("") + '</select></label>' +
      '<label class="bulk-reference">Teams assignment reference<input data-global="teams_reference" minlength="3" maxlength="200" value="' + html(this.global.teams_reference) + '" placeholder="Teams assignment URL or reference"></label>' +
      '<label class="tick-row bulk-confirm"><input type="checkbox" data-global="teams_recorded_confirmed"' + (this.global.teams_recorded_confirmed ? " checked" : "") + '><span>I confirm this feedback has been recorded in Teams for the learners being submitted</span></label>' +
      '<label class="tick-row bulk-confirm"><input type="checkbox" data-global="feedback_required"' + (this.global.feedback_required ? " checked" : "") + '><span>Feedback requires learner action (next step required for each populated row)</span></label>' +
      '</section><p id="draftStatus" role="status" class="bulk-save-status">' + html(this.storageError ? "Local save unavailable: " + this.storageError : "Drafts saved only in this browser") + '</p>' +
      '<div class="bulk-table-wrap"><table class="bulk-table"><thead><tr><th scope="col">Learner</th><th scope="col">Teacher feedback</th><th scope="col">Judgement</th><th scope="col">Work link / next step</th></tr></thead><tbody>' +
      this.learners().map((learner) => this.renderRow(learner)).join("") + '</tbody></table></div>' +
      '<div class="bulk-footer"><p id="bulkResult" role="status" aria-live="polite">Only entered rows will be published. Unconfirmed submissions remain in this browser.</p>' +
      '<button id="bulkSubmit" type="submit" class="button-primary">Submit populated feedback</button></div></form>';
    this.attach();
  }

  renderRow(learner) {
    const row = this.getRow(learner.id);
    const html = escapeHtml;
    const saved = this.justSaved.has(learner.id);
    const readonly = row.uncertain || this.submitting;
    const locked = readonly ? " disabled" : "";
    const judgementOptions = [
      ["", "Select judgement"], ["requires_improvement", "Requires improvement"],
      ["satisfactory", "Satisfactory"], ["good", "Good"],
      ["very_good", "Very good"], ["excellent", "Excellent"],
    ];
    return '<tr data-learner="' + html(learner.id) + '"><th scope="row">' + html(learner.name) +
      '<small class="bulk-row-state">' + (saved ? "Published" : row.uncertain ? "Checking previous submission" : html(row.error || "")) + '</small></th>' +
      '<td><label class="sr-only" for="feedback-' + html(learner.id) + '">Feedback for ' + html(learner.name) + '</label>' +
      '<textarea id="feedback-' + html(learner.id) + '" data-field="feedback_text" rows="3" maxlength="4000" placeholder="Specific, teacher-written feedback"' + locked + '>' + html(row.feedback_text) + '</textarea></td>' +
      '<td><label class="sr-only" for="judgement-' + html(learner.id) + '">Judgement for ' + html(learner.name) + '</label><select id="judgement-' + html(learner.id) +
      '" data-field="judgement"' + locked + '>' + judgementOptions.map(([id, text]) =>
        '<option value="' + id + '"' + (row.judgement === id ? " selected" : "") + '>' + text + '</option>').join("") + '</select></td>' +
      '<td><label class="sr-only" for="work-' + html(learner.id) + '">Link to ' + html(learner.name) + "'s work</label>" +
      '<input id="work-' + html(learner.id) + '" data-field="work_url" type="url" maxlength="500" placeholder="HTTPS Teams / SharePoint link" value="' + html(row.work_url) + '"' + locked + '>' +
      (this.global.feedback_required ? '<label class="sr-only" for="step-' + html(learner.id) + '">Next step for ' + html(learner.name) + '</label>' +
        '<textarea id="step-' + html(learner.id) + '" data-field="next_step" rows="2" maxlength="2000" placeholder="Action for learner"' + locked + '>' + html(row.next_step) + '</textarea>' : '') +
      '</td></tr>';
  }

  attach() {
    const form = $("bulkForm");
    form.addEventListener("input", (event) => this.trackInput(event));
    form.addEventListener("change", (event) => this.trackInput(event));
    $("bulkCohort").addEventListener("change", async (event) => {
      try {
        const cohort = event.target.value;
        const assignment = state.bootstrap.assignments.find((a) => a.cohort_id === cohort)?.id || "";
        await this.switchContext(cohort, assignment);
      } catch (error) { this.setStatus(error.message); }
    });
    $("bulkAssignment").addEventListener("change", async (event) => {
      try { await this.switchContext(this.cohortId, event.target.value); }
      catch (error) { this.setStatus(error.message); }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await this.submit();
    });
  }

  trackInput(event) {
    const input = event.target;
    if (input.id === "bulkCohort" || input.id === "bulkAssignment") return;
    if (input.dataset.global) {
      this.global[input.dataset.global] = input.type === "checkbox" ? input.checked : input.value;
      this.scheduleSave(this.prefix() + "__meta__");
      if (input.dataset.global === "feedback_required" && event.type === "change") this.paint();
      return;
    }
    const learnerId = input.closest("[data-learner]")?.dataset.learner;
    if (!learnerId || !input.dataset.field) return;
    const row = this.getRow(learnerId);
    if (row.uncertain || this.submitting) return;
    row[input.dataset.field] = input.value;
    row.client_key = row.error ? crypto.randomUUID() : row.client_key;
    row.error = "";
    this.justSaved.delete(learnerId);
    this.scheduleSave(this.key(learnerId));
  }

  selectedRows() {
    return [...this.rows.values()].filter((row) => this.learners().some((learner) => learner.id === row.learner_id))
      .filter((row) => !this.justSaved.has(row.learner_id))
      .filter((row) => row.submission || row.feedback_text.trim() || row.judgement || row.work_url || row.next_step.trim());
  }

  buildItem(row) {
    return {
      client_key: row.client_key, cohort_id: this.cohortId, assignment_id: this.assignmentId,
      learner_id: row.learner_id, criterion_id: this.global.criterion_id ? Number(this.global.criterion_id) : null,
      feedback_text: row.feedback_text.trim(), next_step: row.next_step.trim(),
      judgement: row.judgement || null, work_url: row.work_url.trim(),
      teams_reference: this.global.teams_reference.trim(),
      teams_recorded_confirmed: this.global.teams_recorded_confirmed,
      feedback_required: this.global.feedback_required,
    };
  }

  async submit() {
    if (this.submitting) return;
    const rows = this.selectedRows();
    if (!rows.length) return this.setStatus("Enter feedback for at least one learner.");
    if (!this.global.teams_recorded_confirmed || this.global.teams_reference.trim().length < 3) {
      return this.setStatus("Enter a Teams reference and confirm the feedback was recorded there.");
    }
    const items = rows.map((row) => row.submission || this.buildItem(row));
    if (items.some((item) => !item.feedback_text || (item.feedback_required && !item.next_step))) {
      return this.setStatus("Each populated row needs feedback and, if required, a next step.");
    }
    this.submitting = true;
    for (const [i, row] of rows.entries()) {
      row.submission = items[i];
      row.uncertain = true;
      this.scheduleSave(row.key);
    }
    try {
      await this.flush();
    } catch (_) {
      this.submitting = false;
      return;
    }
    this.paint();
    $("bulkSubmit").disabled = true;
    $("bulkResult").textContent = "Submitting " + rows.length + " feedback records…";
    try {
      const response = await api("/api/threads/bulk", { method: "POST", body: JSON.stringify({ items }) });
      for (const result of response.results) {
        const row = rows.find((candidate) => candidate.client_key === result.client_key);
        if (!row) continue;
        if (result.ok) {
          await window.feedbackDraftStore.remove(row.key);
          this.rows.delete(row.learner_id);
          this.justSaved.add(row.learner_id);
        } else {
          row.uncertain = false;
          row.submission = null;
          row.error = result.error || "Unable to save";
          this.scheduleSave(row.key);
        }
      }
      await this.flush();
      this.setStatus(response.saved + " published · " + response.failed + " still need attention");
      $("bulkResult").textContent = response.failed ? "Check the affected rows, then submit again." : "Feedback published. All acknowledged drafts have been cleared.";
    } catch (error) {
      this.setStatus("Connection uncertain. Your drafts remain saved locally; retry to verify before editing.");
      $("bulkResult").textContent = "No confirmation received: " + error.message + ". Retry with the same submission keys.";
    } finally {
      this.submitting = false;
      this.paint();
    }
  }
}

window.bulkFeedback = new BulkFeedbackView();
