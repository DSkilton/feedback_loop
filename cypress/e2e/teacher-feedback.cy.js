describe("Teacher feedback journeys", () => {
  beforeEach(() => {
    cy.visit("/");
    cy.window().then((win) => win.feedbackDraftStore.execute("readwrite", (store) => store.clear()));
    cy.get("#bulkNav").should("be.visible").click();
  });

  it("recovers individual class feedback after a page reload", () => {
    cy.get('[data-learner="learner-1"] [data-field="feedback_text"]')
      .type("Specific feedback is saved locally without pressing Submit.");
    cy.get("#draftStatus").should("contain", "Saved locally");
    cy.reload();
    cy.get("#bulkNav").click();
    cy.get('[data-learner="learner-1"] [data-field="feedback_text"]')
      .should("have.value", "Specific feedback is saved locally without pressing Submit.");
  });

  it("submits a populated row with one click", () => {
    cy.get('[data-global="teams_reference"]').type("Teams class assignment");
    cy.get('[data-global="teams_recorded_confirmed"]').check();
    cy.get('[data-learner="learner-2"] [data-field="feedback_text"]')
      .type("Clear teacher-authored feedback for this learner.");
    cy.get('[data-learner="learner-2"] [data-field="judgement"]').select("good");
    cy.get("#bulkSubmit").click();
    cy.get("#bulkResult").should("contain", "1 published");
    cy.get('[data-learner="learner-2"] .bulk-row-state').should("contain", "Published");
  });

  it("keeps the exact attempted payload when the network response is lost", () => {
    cy.intercept({ method: "POST", url: "/api/threads/bulk", times: 1 }, { forceNetworkError: true }).as("lost");
    cy.get('[data-global="teams_reference"]').type("Teams resilience assignment");
    cy.get('[data-global="teams_recorded_confirmed"]').check();
    cy.get('[data-learner="learner-1"] [data-field="feedback_text"]')
      .type("This row must remain recoverable after a failed network request.");
    cy.get("#bulkSubmit").click();
    cy.wait("@lost");
    cy.get("#bulkResult").should("contain", "Connection uncertain");
    cy.reload();
    cy.get("#bulkNav").click();
    cy.get('[data-learner="learner-1"] [data-field="feedback_text"]')
      .should("contain.value", "must remain recoverable").and("be.disabled");
    cy.get("#bulkSubmit").click();
    cy.get("#bulkResult").should("contain", "1 published");
  });

  it("requires the tutor to select a judgement and write a review before closure", () => {
    cy.get("#boardNav").click();
    cy.get('[data-open="3"]').first().click();
    cy.get("#reviewJudgement").select("very_good");
    cy.get("#reviewNote").type("Strong improvement demonstrated with clear supporting evidence.");
    cy.get('[data-status="CLOSED"]').click();
    cy.get("#toast").should("contain", "Progress updated");
  });

  it("does not provide bulk publishing or tutor closure controls to learners", () => {
    cy.get("#identitySelect").select("learner-1");
    cy.get("#bulkNav").should("not.be.visible");
    cy.get('[data-open="1"]').first().click();
    cy.get('[data-status="CLOSED"]').should("not.exist");
  });
});
