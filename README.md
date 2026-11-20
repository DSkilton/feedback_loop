# Feedback Loop

**Teacher-led feedback, learner-led improvement.**

Feedback Loop is a computing learner co-design project for a potential Middlesbrough College pilot. Its goal is to make feedback a genuine conversation with visible next steps, student progress, and tutor review. Teachers write **all** feedback; the product does **not** generate feedback using AI.

## New prototype

See **[MVP setup and instructions](mvp/README.md)**.

The prototype provides:
- Learner and tutor **Kanban** board with next steps and two-way discussion.
- **Feedback requires student action** checkbox.
- Learner progress evidence when requesting tutor review.
- **Tutor-only** feedback closure and reopening.
- Separate **aggregate QA reporting** dashboard.
- A manually recorded Teams reference for initial assessment feedback.

> **Safety: local synthetic-data demo only.** Identity switching in the prototype is not secure authentication. Do not publish the app, connect it to real learner accounts, or upload student work. Production requires College approval and Microsoft Entra ID security integration.

### Run the MVP locally

~~~bash
python -m pip install -r mvp/requirements.txt
FEEDBACK_LOOP_DEMO_MODE=1 python -m uvicorn mvp.api:app --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000.

PowerShell and full developer instructions are in [mvp/README.md](mvp/README.md).

### Repository branches

- \`master\` — original 2025 Python teaching prototype.
- \`archive/teaching-prototype-2025\` — preserved snapshot of that prototype.
- \`feature/feedback-loop-mvp\` — proposed teacher-led web MVP, tracked in [draft PR #9](https://github.com/DSkilton/feedback_loop/pull/9).

### Development roadmap

Follow the [issues](https://github.com/DSkilton/feedback_loop/issues) for Microsoft Teams/Entra integration, safeguarding/privacy decisions, teacher and learner co-design, accessible UI improvements and production reporting. Feedback Loop is **not ready for a College deployment**.
