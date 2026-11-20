# Teaching cohorts, rubrics and long-term learner targets

**Development branch:** \`feature/cohorts-rubrics-targets\`  
**Status:** synthetic-data pilot only. No live learner data, live roster import or College tenant integration.

## Why these three features fit together

The same learner may receive feedback in several assignments. Tracking feedback per assignment alone loses the longer-term teaching context. We therefore model **who belongs to a group**, **which criterion the tutor is discussing**, and **which improvement goal continues across assignments**.

~~~mermaid
flowchart LR
    Course --> Cohort
    Cohort --> Enrolment
    Enrolment --> Learner
    Enrolment --> Tutor
    Cohort --> Assignment
    Assignment --> Criterion
    Assignment --> Feedback
    Criterion --> Feedback
    Feedback --> TargetLink
    TargetLink --> Target
    Tutor --> Target
    Target --> ReviewHistory
~~~

The teacher creates the feedback and the long-term targets. The system never generates the text.

## 1. Course / cohort enrolments

- Course = the programme or subject, for example Computing.
- Cohort = a defined teaching group in a given academic year.
- Enrolment = a verified **student** or **tutor** membership of one cohort.
- A cohort exposes only its own assignments. Learners can never access a classmate's feedback.
- New feedback requires a tutor, a learner and an assignment to share the same cohort.
- Tutors can see an authorised roster. Students can see the names of their own cohorts but **not** a classmate roster. The QA administrator remains aggregate-only.

The pilot seeds two fictional cohorts so the tests can prove that cross-cohort access is blocked.

**Not yet delivered:** self-service cohort creation, user invitations, roster import and teacher-managed enrolments. These must use an approved College identity/roster source with programme-scoped provisioning. Tutors are **not** allowed to add themselves to arbitrary cohorts or adopt learner accounts. There must be a separate authorised enrolment-management workflow.

## 2. Assignment-specific assessment criteria

Each assignment may have multiple short code/description pairs, for example:

| Assignment | Criterion code | Description |
|---|---|---|
| Java Library System | LO2 | Use abstraction and encapsulation |
| Database Design | LO1 | Design and normalise a relational model |
| Accessible Portfolio | LO3 | Apply accessible interface principles |

A tutor can add a new criterion to an assigned teaching assignment, select it while recording feedback, and write the feedback themselves. The database checks that a chosen criterion actually belongs to that assignment. Legacy short free-text criteria remain supported for older demonstration records.

**Not yet delivered:** institution-wide awarding-body catalogue, version-controlled rubric approval, criterion-level grade mapping or HE policy configuration.

## 3. Persistent improvement targets

A target belongs to one learner, one tutor and one cohort. Unlike assignment feedback, **it is not automatically completed when a single student card moves to 'Ready for review'**.

Tutor workflow:

1. Define a clear target and write personalised guidance.
2. Link relevant feedback from one or more assignments.
3. Discuss the learner's updates and review submitted evidence.
4. Close a linked feedback action after reviewing the work.
5. Mark the target **Achieved**, with a written professional explanation.
6. Reopen the target with a reason if later work shows further development is required.

Learners can read their own targets and linked feedback but cannot create, close, achieve or reopen targets. Tutors can see and review only targets they personally authored for learners in their approved cohort. QA staff see aggregate reports, not named target histories.

The achievement API requires **at least one linked feedback action that a tutor has closed**, plus a written justification of at least 15 characters. There is no automatic learner grading or AI inference.

## Local development and migrations

From the project root:

~~~bash
python -m pip install -r mvp/requirements.txt
python -m pytest -q mvp/tests
node --check mvp/web/app.js
FEEDBACK_LOOP_DEMO_MODE=1 python -m uvicorn mvp.api:app --host 127.0.0.1 --port 8000
~~~

For existing synthetic demo installations, stop the process and **delete only** the local \`feedback_loop_mvp.db\` database before restarting. The newer tables and seed records require a clean demonstration schema. The prototype still uses \`Base.metadata.create_all\`; it is **not a database migration** and must never be used to update a College deployment.

A production-ready successor needs reviewed SQL migrations, cohort import/upsert, approved data ownership, cross-cohort authorisation testing, and a retention/deletion policy.

## Verification

The API tests check:
- tutors cannot create feedback for unenrolled learners or assignments in a different cohort;
- learners and other tutors cannot read feedback or targets outside their remit;
- criteria cannot be attached to the wrong assignment;
- targets persist across multiple assignments and remain learner-read-only;
- only the tutor can mark a target achieved or reopen it;
- target achievement requires completed linked feedback and a written tutor review;
- disabled authentication remains fail-closed.

See [computing learner QA plan](qa-pilot.md) for manual accessibility and classroom testing. **The automated tests do not replace browser/keyboard QA or College IT/DPO approval.**
