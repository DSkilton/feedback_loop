# Computing learner and tutor QA pilot

## Purpose

Test whether the Feedback Loop Kanban board makes feedback easier to **understand, act on and discuss**. Feedback remains teacher-authored. The application must not replace a tutor's professional judgement or pastoral relationship.

## Suggested roles and session

- Two to five volunteer computing learners plus one or two computing tutors.
- One tutor moderates the practice dataset and observes usability rather than assessing individual learners.
- Approximately a short classroom workshop with think-aloud discussion and an anonymous usability questionnaire, when approved through College processes.
- Record reproducible bugs without naming learners or including work samples.

## Learner tasks

- [ ] Locate the next step on a Java/database assignment.
- [ ] Explain in their own words what the tutor is asking them to improve.
- [ ] Move an action to **In progress** using mouse **and keyboard**.
- [ ] Leave a question for the tutor, then find the reply in the timeline.
- [ ] Attach a small PDF/TXT evidence file and describe what it shows.
- [ ] Submit an improvement for tutor review with a short explanation of their changes.
- [ ] Verify that the learner **cannot close** the feedback loop.
- [ ] Check the experience at phone, tablet and desktop widths.
- [ ] Describe which labels, symbols or steps are confusing or unnecessary.

## Tutor tasks

- [ ] Confirm the initial feedback reference in Teams.
- [ ] Create a teacher-authored entry in Feedback Loop with its Teams reference.
- [ ] Try to submit the entry without confirming initial feedback was recorded in Teams; it should be rejected.
- [ ] Set **Feedback requires student action** and include one short, actionable next step.
- [ ] Review evidence from an assigned learner and return work for improvements.
- [ ] Close a reviewed action, then reopen it and explain the reason.
- [ ] Mark the same development focus on **two different assignments** and locate it in the recurring focus panel.
- [ ] Discuss whether the focus panel improves tutor conversations or risks being misunderstood as a judgement about the learner.

## Quality / IT tests

- [ ] Admin sees **aggregate** statistics but not individual feedback, evidence or private pastoral records.
- [ ] Another learner cannot view or download a classmate's attachments.
- [ ] Executable, HTML, renamed-file and oversized uploads are rejected.
- [ ] Anonymous requests and untrusted identity headers are rejected when development mode is disabled.
- [ ] Navigate the entire interface with keyboard only; assess focus order, labels and visibility.
- [ ] Check screen reader announcements and contrast against WCAG 2.2 AA.
- [ ] No requests are sent to an AI model or an external student-feedback service.

## Learner feedback questions

1. Could you find what to do next without help?
2. What did you think **Ready for review** meant?
3. Could you identify who decides whether an improvement is complete?
4. Did the timeline help explain the feedback conversation?
5. Did you feel the teacher's own words were clear and personal?
6. What should be changed before this is offered to more learners?

**Pass criteria:** every learner can locate the next action; no learner can close their own action; all identified student-data access violations are blocked; any confusing interaction becomes a tracked GitHub issue with a clear reproduction case.

The learner QA report should summarise patterns, not individual responses. This is a co-design activity, not a measurement of student ability.
