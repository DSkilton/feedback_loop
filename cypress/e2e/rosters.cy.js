describe("Spreadsheet roster onboarding", () => {
  it("previews and imports a synthetic class without replacing existing enrolments", () => {
    cy.visit("/");
    cy.get("#identitySelect").select("admin-1");
    cy.get("#identitySelect").should("not.be.disabled");
    cy.get("#rosterNav").should("be.visible").click();
    cy.get("#rosterFile").selectFile({
      contents:Cypress.Buffer.from("course_id,cohort_id,cohort_name,academic_year,user_id,name,member_role\ncomputing,roster-browser,Spreadsheet class,2026/27,roster-learner,Spreadsheet Learner,learner\ncomputing,roster-browser,Spreadsheet class,2026/27,tutor-2,Sam Patel,tutor"),
      fileName:"roster.csv",mimeType:"text/csv"
    });
    cy.get("#rosterForm button").click();
    cy.get("#rosterPreview").should("contain","Ready to import").and("contain","2 new memberships");
    cy.get("#rosterCommit").click();
    cy.get("#rosterPreview").should("contain","Import complete");
    cy.get("#identitySelect").select("tutor-2");
    cy.get("#identitySelect").should("not.be.disabled");
    cy.get("#app").should("contain","Spreadsheet class").and("contain","Spreadsheet Learner");
    cy.get("#rosterNav").should("not.be.visible");
  });
});
