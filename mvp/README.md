# Feedback Loop — Computing pilot

A **teacher-led** platform for closing the feedback loop. The learner and tutor interface is a responsive Kanban board; the quality-assurance interface is a separate aggregate reporting dashboard.

**Never use this demo with real student data.** The current authentication deliberately uses switchable synthetic identities. It is NOT secure authentication and must never be deployed to the College network or exposed on a public IP. College IT approval, Microsoft Entra ID integration, role mapping, data-protection review, accessibility testing and production database migrations are required first.

## Principles

- Teachers write all feedback themselves. **No AI-generated feedback.**
- Teachers record initial assessment feedback in **Microsoft Teams and Feedback Loop** during the manual pilot. The app stores a Teams assignment reference; it does **not** sync with Teams yet.
- Follow-up comments and next-step progress take place in Feedback Loop.
- A tutor ticks **Feedback requires student action** to create a learner action. If unticked, it is shared for information only.
- Learners can advance or revise their work but cannot close the loop. A tutor must review and explicitly close it.
- When a learner requests tutor review they must explain what they changed; the explanation is stored in the progress timeline.
- Individual student boards are private. Admin users have only aggregate reporting in the MVP.
- Pastoral notes are intentionally **not included** in the prototype. They require a separate restricted permission model, retention rules and safeguarding review before being developed.

## Run locally

Python 3.11+ is recommended.

~~~bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r mvp/requirements.txt
FEEDBACK_LOOP_DEMO_MODE=1 python -m uvicorn mvp.api:app --host 127.0.0.1 --port 8000
~~~

On Windows PowerShell, set the environment variable first:

~~~powershell
$env:FEEDBACK_LOOP_DEMO_MODE="1"
python -m uvicorn mvp.api:app --host 127.0.0.1 --port 8000
~~~

Open <http://127.0.0.1:8000>. The app seeds a small set of fictional computing learners, a tutor and a QA administrator. Identity switching is for demonstration only. The SQLite file \`feedback_loop_mvp.db\` is local and must not be committed.

## Tests

~~~bash
pytest -q mvp/tests
node --check mvp/web/app.js
~~~

The previous teaching prototype remains on branch \`archive/teaching-prototype-2025\`, with its source still on the original \`master\` until this work is reviewed.

## Workflow

\`Action required → In progress → Ready for review → Completed\`

- Learner: Action required ↔ In progress ↔ Ready for review (within the supported transitions).
- Tutor: review submitted work, return it for more work, or close it. Tutor can reopen a closed loop.
- Information-only feedback does not enter the actionable board and can be marked reviewed by a tutor.
- Every status change is recorded in a timeline. Tutor and learner can add comments.
- Quality reporting shows aggregate counts and tutor-tagged focus areas, not individual pastoral notes.

## Deliberately out of scope for this MVP

Real logins; Graph/Teams synchronisation; assignment roster integration; automatic reminders; learner evidence uploads; genuine pastoral records; multi-tutor permission mapping; deadlines; production migration tooling; exports and retention policy. These are tracked in GitHub issues #4–#8 and require College agreement.

## Learner QA

Start with a supervised computing learner and tutor usability session using **synthetic data**. Collect clarity, accessibility, mobile and feedback-loop progression findings without posting student-identifiable information to GitHub.
