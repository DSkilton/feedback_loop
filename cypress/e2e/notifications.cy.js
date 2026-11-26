describe("Notification inbox", () => {
  it("delivers a durable notification to the intended learner and opens the feedback", () => {
    cy.request({method:"POST",url:"/api/threads",headers:{"X-Demo-User":"tutor-1"},body:{
      assignment_id:"java",cohort_id:"computing-26",learner_id:"learner-1",
      feedback_text:"Notification browser journey",feedback_required:false,teams_reference:"Demo assignment",teams_recorded_confirmed:true
    }}).its("status").should("eq",201);
    cy.visit("/");
    cy.get("#identitySelect").select("learner-1");
    cy.get("#identitySelect").should("not.be.disabled");
    cy.get("#notificationsNav").should("be.visible").click();
    cy.get("#app").should("contain", "New teacher feedback is available.");
    cy.get("[data-notification-id]").first().click();
    cy.get("#threadDetail").should("contain", "Notification browser journey");
    cy.get('[data-close="threadDialog"]').click();
    cy.get("#notificationReadAll").click();
    cy.get("#app").should("contain", "0 unread");
  });
});
