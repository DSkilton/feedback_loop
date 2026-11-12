"""Feedback lifecycle state machine: pure domain rules, no HTTP or database code.

A learner can prepare work and ask for review, but only the assigned tutor can
approve/close a feedback loop. A zero-action information item is tutor-closable.
"""
from __future__ import annotations

from dataclasses import dataclass

ACTION_REQUIRED = "ACTION_REQUIRED"
IN_PROGRESS = "IN_PROGRESS"
READY_FOR_REVIEW = "READY_FOR_REVIEW"
CLOSED = "CLOSED"
INFORMATION = "INFORMATION"

STATES = (ACTION_REQUIRED, IN_PROGRESS, READY_FOR_REVIEW, CLOSED, INFORMATION)

LEARNER_TRANSITIONS = frozenset({
    (ACTION_REQUIRED, IN_PROGRESS),
    (IN_PROGRESS, ACTION_REQUIRED),
    (IN_PROGRESS, READY_FOR_REVIEW),
    (READY_FOR_REVIEW, IN_PROGRESS),
})
TUTOR_TRANSITIONS = frozenset({
    (READY_FOR_REVIEW, CLOSED),
    (INFORMATION, CLOSED),
    (READY_FOR_REVIEW, IN_PROGRESS),
    (CLOSED, ACTION_REQUIRED),
    (CLOSED, INFORMATION),
    # Tutor-directed guidance, with no implicit approval.
    (ACTION_REQUIRED, IN_PROGRESS),
    (IN_PROGRESS, READY_FOR_REVIEW),
})


class TransitionRejected(ValueError):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class TransitionDecision:
    previous: str
    target: str
    tutor_approved: bool
    progress_note: str


class FeedbackStateMachine:
    """Single source of truth for role-sensitive feedback transitions."""

    def decide(self, *, current: str, target: str, actor_role: str,
               feedback_required: bool, progress_note: str = "") -> TransitionDecision:
        note = progress_note.strip()
        if current not in STATES or target not in STATES:
            raise TransitionRejected(409, "Unknown feedback state.")
        if actor_role == "learner":
            if not feedback_required or (current, target) not in LEARNER_TRANSITIONS:
                raise TransitionRejected(403, "Learners can progress work but cannot close it.")
            if target == READY_FOR_REVIEW and not note:
                raise TransitionRejected(422, "Explain what you changed before requesting review.")
        elif actor_role == "tutor":
            if current == CLOSED and target in (ACTION_REQUIRED, INFORMATION):
                correct_state = ACTION_REQUIRED if feedback_required else INFORMATION
                if target != correct_state:
                    raise TransitionRejected(409, "Reopen feedback in its original action category.")
            if (current, target) not in TUTOR_TRANSITIONS:
                raise TransitionRejected(409, "That tutor transition is not permitted.")
        else:
            raise TransitionRejected(403, "Only tutors and learners can update work.")
        return TransitionDecision(
            previous=current, target=target,
            tutor_approved=(actor_role == "tutor" and target == CLOSED),
            progress_note=note if actor_role == "learner" and target == READY_FOR_REVIEW else "",
        )
