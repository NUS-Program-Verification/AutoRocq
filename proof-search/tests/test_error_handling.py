"""
Error paths that reported the wrong thing, or nothing.

Three shapes turned up in the audit of this project's `except` handlers:

  - validation written as an assert and then caught (`python -O` deletes the
    check and the fallback with it),
  - a handler that returns a plausible-looking value without logging or
    recording anything, so the failure is invisible,
  - two layers each inventing their own error text for the same failure, the
    outer one overwriting what the inner one carefully worked out.

Pure unit tests: no Rocq, no model.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager


class StubSession:
    def __init__(self, messages):
        self.messages = messages


class StubManager:
    def __init__(self, messages):
        self.chat_session = StubSession(messages)


ANSWERED = [{"role": "assistant", "tool_calls": [{"id": "call_1"}]}]


def problem(messages, tool_call_id="call_1"):
    return ContextManager._tool_role_problem(StubManager(messages), tool_call_id)


def test_a_well_formed_tool_response_has_no_problem():
    assert problem(ANSWERED) is None


def test_every_rejection_says_why_in_words():
    """Each of these was an assert message; they are return values now."""
    cases = [
        (ANSWERED, None, "tool_call_id is required"),
        ([], "call_1", "empty message thread"),
        ([{"role": "user", "content": "hi"}], "call_1", "must be an assistant message"),
        ([{"role": "assistant", "content": "hi"}], "call_1", "must have tool_calls"),
        ([{"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]}], "call_1",
         "exactly one tool call"),
    ]
    for messages, tool_call_id, expected in cases:
        reason = problem(messages, tool_call_id)
        assert reason is not None, f"{messages} was accepted"
        assert expected in reason, reason


def test_the_checks_survive_python_o():
    """The point of the change: an assert would be gone under -O.

    Nothing here asserts, so the validation still runs when assertions are
    stripped -- which is when a malformed tool response would otherwise reach
    the API and be rejected there instead.
    """
    import subprocess

    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from agent.context_manager import ContextManager\n"
        "class S:\n"
        "    messages = []\n"
        "class M:\n"
        "    chat_session = S()\n"
        "print(ContextManager._tool_role_problem(M(), None))\n"
    ) % str(PROJECT_ROOT)

    out = subprocess.run([sys.executable, "-O", "-c", script],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "tool_call_id is required" in out.stdout, out.stdout
