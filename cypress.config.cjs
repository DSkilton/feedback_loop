const { defineConfig } = require("cypress");

module.exports = defineConfig({
  e2e: {
    baseUrl: "http://127.0.0.1:8000",
    specPattern: "cypress/e2e/**/*.cy.js",
    supportFile: false,
    setupNodeEvents(on) {
      on("task", {
        diagnostic(message) {
          console.log("[cypress-diagnostic] " + message);
          return null;
        },
      });
    },
    defaultCommandTimeout: 10000,
  },
  video: false,
});
