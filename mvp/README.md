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
- Students and tutors belong to an approved **teaching cohort**. Tutors see only assigned learners and cohort assignments. A second fictional cohort is included to test access boundaries.
- Tutors can select assignment-specific **assessment criteria/rubrics** and write short personal feedback against them.
- Teachers can create long-term **learner improvement targets**, link feedback from several assignments, then confirm achievement or reopen the target with a written professional judgement. Learners can read their own targets but cannot close them.
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

Open <http://127.0.0.1:8000>. The app seeds two different fictional computing cohorts with tutors, learners, sample rubrics, a long-term improvement target and a QA administrator. Identity switching is for demonstration only. The SQLite file \`feedback_loop_mvp.db\` is local and must not be committed. For schema changes in the synthetic demo, delete the demo database file to regenerate it; this is **not** a production migration strategy.

## Tests

~~~bash
python -m pytest -q mvp/tests
node --check mvp/web/app.js
~~~

Read [cohort, rubric and long-term target architecture](docs/learning-foundations.md) for the data model, teacher workflows and access rules.

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

Live College authentication and a **verified, IT-managed roster** (although an optional Entra OIDC scaffold and synthetic cohort memberships exist); Graph/Teams synchronisation; automatic reminders; genuine pastoral records; programme-lead enrolment administration; multi-tutor permission mapping; deadlines; antivirus scanning and secure evidence storage; production migration tooling; exports and retention policy. These remain tracked in GitHub issues and require College agreement.

## Learner QA

Start with a supervised computing learner and tutor usability session using **synthetic data**. Collect clarity, accessibility, mobile and feedback-loop progression findings without posting student-identifiable information to GitHub.
