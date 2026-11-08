# Feedback Loop — Computing pilot

A **teacher-led** platform for closing the feedback loop. The learner and tutor interface is a responsive Kanban board; the quality-assurance interface is a separate aggregate reporting dashboard.

**Never use this demo with real student data.** The current authentication deliberately uses switchable synthetic identities. It is NOT secure authentication and must never be deployed to the College network or exposed on a public IP. College IT approval, Microsoft Entra ID integration, role mapping, data-protection review, accessibility testing and production database migrations are required first.

## Principles

- Teachers write all feedback themselves. **No AI-generated feedback.**
- Teachers record initial assessment feedback in **Microsoft Teams and Feedback Loop**. They must tick a **manual Teams confirmation** box when adding the next step; Teams class/assignment/submission IDs are optional to prevent exact duplicates. There is **no automatic Teams sync**.
- Follow-up comments and next-step progress take place in Feedback Loop.
- A tutor ticks **Feedback requires student action** to create a learner action. If unticked, it is shared for information only.
- Learners can advance or revise their work but cannot close the loop. A tutor must review and explicitly close it.
- When a learner requests tutor review they must explain what they changed; the explanation is stored in the progress timeline.
- Learners can attach small **PDF, PNG, JPEG and TXT evidence files** (up to 2 MiB each, five per action) on their own active feedback. Downloads remain private to the learner and their tutor.
- Tutors see **recurring development focus tags** when they have marked the same area on at least two different assignments for a learner. These are professional observations, never AI-inferred weaknesses.
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

Open <http://127.0.0.1:8000>. The app seeds a small set of fictional computing learners, a tutor and a QA administrator. Identity switching is for demonstration only. The SQLite file \`feedback_loop_mvp.db\` is local and must not be committed. For schema changes in the synthetic demo, delete the demo database file to regenerate it; this is **not** a production migration strategy.

## Tests

~~~bash
python -m pytest -q mvp/tests
node --check mvp/web/app.js
~~~

## Architecture and design patterns

See **[State Machine, Observer and CQRS-style read models](docs/design-patterns.md)** for the diagram, transition table and SOLID rationale.

- `mvp/workflow.py` centrally controls valid learner/tutor state transitions. Only a tutor may close feedback.
- `mvp/events.py` publishes typed changes to independent, synchronous audit and reporting observers.
- `mvp/reporting.py` maintains aggregate counters in the same database transaction; the QA dashboard reads counters without scanning individual feedback each time.
- `mvp_domain_events` records structured workflow provenance, including explicit tutor approval of closure.
- These improvements retain the existing browser interface and do **not** introduce full event sourcing, external messaging or automatic feedback writing.

The new `mvp_report_counters` and `mvp_domain_events` tables are created automatically for a local demo; an existing synthetic demo database is backfilled once. Schema migrations and concurrency/security review are still required for any production deployment.

Read [College integration and release gates](docs/college-integration.md) before attempting any Entra ID configuration. **Sign-in is disabled by default;** Entra requires approved tenant configuration, app roles and an offline mapping to already-enrolled local users. That login scaffold has not been tested against the live College tenant.

The previous teaching prototype remains on branch \`archive/teaching-prototype-2025\`, with its source still on the original \`master\` until this work is reviewed.

## Workflow

\`Action required → In progress → Ready for review → Completed\`

- Learner: Action required ↔ In progress ↔ Ready for review (within the supported transitions).
- Tutor: review submitted work, return it for more work, or close it. Tutor can reopen a closed loop.
- Information-only feedback does not enter the actionable board and can be marked reviewed by a tutor.
- Every status change is recorded in a timeline. Tutor and learner can add comments.
- Quality reporting shows aggregate counts and tutor-tagged focus areas, not individual pastoral notes.

## Deliberately out of scope for this MVP

Live College authentication and a verified roster (although an **optional Entra OIDC scaffold** now exists); Graph/Teams synchronisation; automatic reminders; genuine pastoral records; multi-tutor permission mapping; deadlines; antivirus scanning and secure evidence storage; production migration tooling; exports and retention policy. These are tracked in GitHub issues #4–#8 and require College agreement.

## Learner QA

Start with a supervised computing learner and tutor usability session using **synthetic data**. Collect clarity, accessibility, mobile and feedback-loop progression findings without posting student-identifiable information to GitHub.
