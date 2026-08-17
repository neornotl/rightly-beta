"""Dialogue state machine.

States:
  WELCOME, DISCLAIMER, LISTENING, TRANSCRIBING, RETRIEVING, SAFETY_CHECK,
  HOLDING, SPEAKING, CLARIFYING, ESCALATING, DONE, ERROR

Transitions are validated in a single table; invalid transitions raise
:class:`TransitionError`. The machine drives the CLI/UI and is fully testable.
"""

from __future__ import annotations

from enum import Enum

from app.schemas import PipelineResult


class State(str, Enum):
    WELCOME = "WELCOME"
    DISCLAIMER = "DISCLAIMER"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    RETRIEVING = "RETRIEVING"
    SAFETY_CHECK = "SAFETY_CHECK"
    HOLDING = "HOLDING"
    SPEAKING = "SPEAKING"
    CLARIFYING = "CLARIFYING"
    ESCALATING = "ESCALATING"
    CONNECTING = "CONNECTING"
    DONE = "DONE"
    ERROR = "ERROR"


class TransitionError(ValueError):
    """Raised on invalid state transitions."""


_EDGES: dict[State, set[State]] = {
    State.WELCOME: {State.DISCLAIMER, State.DONE, State.ERROR},
    State.DISCLAIMER: {State.LISTENING, State.WELCOME, State.DONE, State.ERROR},
    State.LISTENING: {
        State.TRANSCRIBING,
        State.CLARIFYING,
        State.ESCALATING,
        State.CONNECTING,
        State.DONE,
        State.ERROR,
        State.WELCOME,
    },
    State.TRANSCRIBING: {State.RETRIEVING, State.CLARIFYING, State.ERROR, State.LISTENING},
    State.RETRIEVING: {State.SAFETY_CHECK, State.CLARIFYING, State.ERROR, State.LISTENING},
    State.SAFETY_CHECK: {
        State.HOLDING,
        State.SPEAKING,
        State.CLARIFYING,
        State.ESCALATING,
        State.ERROR,
        State.LISTENING,
    },
    State.HOLDING: {State.SPEAKING, State.CLARIFYING, State.ESCALATING, State.ERROR},
    State.SPEAKING: {
        State.LISTENING,
        State.SPEAKING,
        State.CLARIFYING,
        State.DONE,
        State.ERROR,
        State.ESCALATING,
        State.CONNECTING,
    },
    State.CLARIFYING: {State.LISTENING, State.DONE, State.ERROR, State.SPEAKING},
    State.ESCALATING: {State.LISTENING, State.DONE, State.ERROR},
    State.CONNECTING: {State.LISTENING, State.SPEAKING, State.DONE, State.ERROR},
    State.DONE: {State.WELCOME, State.ERROR},
    State.ERROR: {State.WELCOME, State.LISTENING, State.DONE},
}


class DialogueStateMachine:
    """Validated conversation state transitions."""

    def __init__(self, start: State = State.WELCOME):
        self._state = start
        self.history: list[State] = [start]
        self.last_result: PipelineResult | None = None
        self.last_speech: str | None = None

    @property
    def state(self) -> State:
        return self._state

    def can_transition(self, target: State) -> bool:
        return target in _EDGES.get(self._state, set())

    def transition(self, target: State) -> State:
        if target == self._state:
            return self._state
        if target not in _EDGES.get(self._state, set()):
            raise TransitionError(f"Invalid transition {self._state.value} -> {target.value}")
        self._state = target
        self.history.append(target)
        return self._state

    def reset(self, start: State = State.WELCOME) -> None:
        self._state = start
        self.history = [start]
        self.last_result = None
        self.last_speech = None

    def is_terminal(self) -> bool:
        return self._state in {State.DONE, State.ERROR}

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DialogueStateMachine(state={self._state.value})"
