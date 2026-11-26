/* Preview-first roster import for authorised organisation administrators. */
(() => {
  const header = "course_id,cohort_id,cohort_name,academic_year,user_id,name,member_role";
  function render() {
    if (!state.bootstrap.can_manage_organisation) return;
    const id = state.bootstrap.user.id;
    const here = () => state.page === "rosters" && state.bootstrap?.user.id === id;
    const esc = escapeHtml;
    let preview = null;
    let selected = null;
    $("app").innerHTML = '<section class="page-heading"><div><div class="eyebrow">ORGANISATION</div><h1>Roster import</h1><p>Preview and import classes and memberships from a spreadsheet.</p></div></section>' +
      '<section class="report-panel"><h2>Upload roster</h2><p>Use a UTF-8 CSV or single-sheet Excel (.xlsx) file. Format all IDs as text; leading zeros must be preserved. Courses and tutor accounts must already exist.</p>' +
      '<button class="button-ghost" id="rosterTemplate" type="button">Download CSV template</button>' +
      '<form class="feedback-form" id="rosterForm"><label>Roster file<input type="file" id="rosterFile" accept=".csv,.xlsx" required></label><button class="button-primary" type="submit">Preview import</button></form>' +
      '<div id="rosterPreview" role="status"></div></section>';
    $("rosterTemplate").addEventListener("click", () => {
      const blob = new Blob([header + "\r\n"], {type:"text/csv;charset=utf-8"});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "feedback-loop-roster-template.csv";
      link.click();
      URL.revokeObjectURL(url);
    });
    $("rosterFile").addEventListener("change", () => {
      preview = null;
      selected = null;
      $("rosterPreview").textContent = "";
    });
    async function upload(file, digest = "") {
      const body = new FormData();
      body.append("file", file);
      if (digest) body.append("expected_sha256", digest);
      return api("/api/organisation/rosters", {method:"POST", body});
    }
    function show(result) {
      $("rosterPreview").innerHTML = '<section class="detail-section"><h3>' + (result.imported ? "Import complete" : result.valid ? "Ready to import" : "Correct the file before importing") + '</h3>' +
        '<p>' + result.row_count + ' valid-format rows · ' + result.new_cohorts + ' new classes · ' + result.new_learners + ' new learner accounts · ' + result.new_memberships + ' new memberships · ' + result.unchanged + ' unchanged</p>' +
        (result.error_count ? '<p class="form-error">' + result.error_count + ' validation errors</p><ul>' + result.errors.map(e => '<li>Row ' + e.row + ': ' + esc(e.message) + '</li>').join("") + '</ul>' : '') +
        (result.preview.length ? '<div style="overflow-x:auto"><table><thead><tr><th>Course</th><th>Class</th><th>Year</th><th>Account ID</th><th>Name</th><th>Role</th></tr></thead><tbody>' +
          result.preview.map(r => '<tr><td>' + esc(r.course_id) + '</td><td>' + esc(r.cohort_name) + '</td><td>' + esc(r.academic_year) + '</td><td>' + esc(r.user_id) + '</td><td>' + esc(r.name) + '</td><td>' + esc(r.member_role) + '</td></tr>').join("") + '</tbody></table></div>' : '') +
        (result.preview_truncated ? '<p class="quiet">Showing the first 50 rows. All rows were validated.</p>' : '') +
        (result.valid && !result.imported ? '<p class="quiet">This adds classes and memberships; it never removes existing members or changes account roles.</p><button type="button" class="button-primary" id="rosterCommit">Confirm import</button>' : '') + '</section>';
      $("rosterCommit")?.addEventListener("click", async event => {
        const button = event.currentTarget;
        const file = selected;
        const digest = preview?.sha256;
        button.disabled = true;
        $("rosterFile").disabled = true;
        $("rosterForm").querySelector("button").disabled = true;
        try {
          const committed = await upload(file, digest);
          if (!here()) return;
          preview = null;
          selected = null;
          show(committed);
        } catch (error) { if (here()) notify(error.message); }
        finally {
          if (here()) {
            button.disabled = false;
            $("rosterFile").disabled = false;
            $("rosterForm").querySelector("button").disabled = false;
          }
        }
      });
    }
    $("rosterForm").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const file = $("rosterFile").files[0];
      if (!file) return;
      form.querySelector("button").disabled = true;
      $("rosterFile").disabled = true;
      $("rosterPreview").textContent = "Validating roster…";
      try {
        const result = await upload(file);
        if (!here()) return;
        preview = result;
        selected = file;
        show(result);
      } catch (error) {
        if (here()) $("rosterPreview").textContent = error.message;
      } finally {
        if (here()) { form.querySelector("button").disabled = false; $("rosterFile").disabled = false; }
      }
    });
  }
  window.rosterImport = {render};
})();
