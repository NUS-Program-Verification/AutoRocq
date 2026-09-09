import subprocess
import sys
from pathlib import Path

from agent.context_manager import ContextManager


PROJECT_ROOT = Path(__file__).parent.parent


class StubSession:
    def __init__(self, messages):
        self.messages = messages


class StubManager:
    def __init__(self, messages):
        self.chat_session = StubSession(messages)


ANSWERED = [{"role": "assistant", "tool_calls": [{"id": "call_1"}]}]


def problem(messages, tool_call_id="call_1"):
    return ContextManager._tool_role_problem(StubManager(messages), tool_call_id)


def test_well_formed_tool_response_is_valid():
    assert problem(ANSWERED) is None


def test_invalid_tool_responses_explain_the_problem():
    cases = [
        (ANSWERED, None, "tool_call_id is required"),
        ([], "call_1", "empty message thread"),
        ([{"role": "user"}], "call_1", "must be an assistant message"),
        ([{"role": "assistant"}], "call_1", "must have tool_calls"),
        (
            [{"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]}],
            "call_1",
            "exactly one tool call",
        ),
    ]

    for messages, tool_call_id, expected in cases:
        assert expected in problem(messages, tool_call_id)


def test_validation_survives_optimized_python():
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from agent.context_manager import ContextManager\n"
        "class S:\n"
        "    messages = []\n"
        "class M:\n"
        "    chat_session = S()\n"
        "print(ContextManager._tool_role_problem(M(), None))\n"
    ) % str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "tool_call_id is required" in result.stdout
