# Computing learner and tutor QA pilot

**Only synthetic data. Do not enter actual learner identities, academic work, safeguarding information or pastoral notes in this prototype.**

## Purpose

Test whether the Feedback Loop Kanban board makes feedback easier to **understand, act on and discuss**. Feedback remains teacher-authored. The application must not replace a tutor's professional judgement or pastoral relationship.

## Suggested roles and session

- Two to five volunteer computing learners plus one or two computing tutors.
- One tutor moderates the synthetic dataset and observes use; no individual learner is assessed or scored.
- Approximately a short classroom workshop with think-aloud discussion and an anonymous usability questionnaire, when approved through College processes.
- Report bugs to GitHub **without student-identifying details**, using fake names and fictitious assignment material.

## Learner tasks

- [ ] Locate the next step on a synthetic Java/database assignment.
- [ ] Explain in their own words what the tutor is asking them to improve.
- [ ] Move an action to **In progress** using mouse **and keyboard**.
- [ ] Leave a question for the tutor, then find the reply in the timeline.
- [ ] Add a tiny synthetic PDF/TXT evidence file and describe what it shows.
- [ ] Submit an improvement for tutor review with a short explanation of their changes.
- [ ] Verify that the learner **cannot close** the feedback loop.
- [ ] Check the experience at phone, tablet and desktop widths.
- [ ] Describe which labels, symbols or steps are confusing or unnecessary.

## Tutor tasks

- [ ] Record fictional initial feedback in Teams (or use a synthetic reference).
- [ ] Create a teacher-authored entry in Feedback Loop with the Teams reference.
- [ ] Try to submit the entry without confirming initial feedback was recorded in Teams; it should be rejected.
- [ ] Set **Feedback requires student action** and include one short, actionable next step.
- [ ] Review evidence from an assigned fictional student and return work for improvements.
- [ ] Close a reviewed action, then reopen it and explain the reason.
- [ ] Mark the same development focus on **two different assignments** and locate it in the recurring focus panel.
- [ ] Discuss whether the focus panel improves tutor conversations or risks being misunderstood as a judgement about the learner.

## Course, criterion and long-term target QA

- [ ] Compare tutor Jo Morgan's Computing Pilot A cohort against tutor Sam Patel's Pilot B cohort. Neither should see the other's learner feedback.
- [ ] Check that the learner cohort view contains no classmate roster.
- [ ] Tutor selects a Java assignment criterion from the rubric and writes personal feedback in their own words.
- [ ] Tutor adds a new criterion code and description for an authorised assignment.
- [ ] Tutor creates a long-term improvement target and links feedback from **two different assignments**.
- [ ] Learner can see the target and assignments, but cannot mark the target achieved.
- [ ] Tutor cannot mark the target achieved until at least one linked feedback action has been closed.
- [ ] Tutor writes a short professional explanation, marks the target achieved, and can reopen it with another explanation.
- [ ] Verify that manually tagged repeated needs are separated by teaching cohort.
- [ ] Ask whether the distinction between a one-off feedback **action** and a longer-term **target** is clear to learners.
- [ ] Demonstrate that no teacher or learner can self-enrol into another cohort.

## Quality / IT tests

- [ ] Admin sees **aggregate** statistics but not individual feedback, evidence or private pastoral records.
- [ ] Another learner cannot view or download a classmate's attachments.
- [ ] Executable, HTML, renamed-file and oversized uploads are rejected.
- [ ] Anonymous requests and fake identity headers are rejected when demo mode is disabled.
- [ ] Navigate the entire interface with keyboard only; assess focus order, labels and visibility.
- [ ] Check screen reader announcements and contrast against WCAG 2.2 AA.
- [ ] No requests are sent to an AI model or an external student-feedback service.
- [ ] Do not run a live College tenant or real student-data pilot until College IT and DPO approval.

## Learner feedback questions

1. Could you find what to do next without help?
2. What did you think **Ready for review** meant?
3. Could you identify who decides whether an improvement is complete?
4. Did the timeline help explain the feedback conversation?
5. Did you feel the teacher's own words were clear and personal?
6. What should be changed before this is offered to more learners?

**Pass criteria:** every learner can locate the next action; no learner can close their own action; all identified student-data access violations are blocked; any confusing interaction becomes a tracked GitHub issue with a clear reproduction case.

The learner QA report should summarise patterns, not individual responses. This is a co-design activity, not a measurement of student ability.
