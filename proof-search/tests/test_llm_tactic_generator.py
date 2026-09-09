"""
ContextManager: what it wires up at construction, and the initial prompt it
builds for the model.

Each test used to collect its checks into a dict, print a tick or a cross per
entry, and return the conjunction. pytest ignores that return, so a
ContextManager with no chat session, no history and no model passed exactly
like a working one -- as did the `except Exception` paths, which returned False
after printing a traceback.

These stay behind the `llm` marker. Nothing here calls the API -- ContextManager
and CoqChatSession only assemble a system prompt at construction -- but the
marker was added deliberately after a plain `pytest` run was seen billing for
real, so unmarking it is a decision for whoever owns the key, not this cleanup.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager
from agent.proof_tree import ProofTree
from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"

# conftest.py skips these unless --runllm is passed.
pytestmark = pytest.mark.llm


@pytest.fixture
def config():
    """Config used by the tests below; they only read config.llm.api_key.

    Skips rather than fails when no key is configured: --runllm asks for these
    to run, but an unconfigured checkout should not go red for it.
    """
    loaded = ProofAgentConfig.from_file(str(config_file))
    if not (getattr(loaded.llm, "api_key", None) or os.getenv("OPENAI_API_KEY")):
        pytest.skip("needs an LLM API key")
    return loaded


@pytest.fixture
def coq():
    interface = CoqInterface(str(temp_example_copy("example.v")))
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_context_manager_wires_up_its_collaborators(config, coq):
    """Everything the controller reads off a ContextManager has to be there."""
    cm = ContextManager(coq, api_key=config.llm.api_key)

    assert cm.coq is coq
    assert cm.chat_session is not None
    assert cm.tactic_history is not None
    assert cm.model, "no model resolved"
    assert cm.chat_session.model == cm.model or cm.chat_session.model.endswith(cm.model)
    assert cm.context_search is not None, "context search failed to initialise"

    # The chat session opens with a system prompt and the tools it advertises.
    assert cm.chat_session.messages, "the session has no system prompt"
    assert cm.chat_session.messages[0]["role"] == "system"
    tool_names = {t["function"]["name"] for t in cm.chat_session.tools}
    assert {"plan", "tactic"} <= tool_names, tool_names


def test_disabling_context_search_removes_the_query_tool(config, coq):
    """The flag has to reach the tool list the model is offered."""
    with_search = ContextManager(coq, api_key=config.llm.api_key, enable_context_search=True)
    without = ContextManager(coq, api_key=config.llm.api_key, enable_context_search=False)

    names = lambda cm: {t["function"]["name"] for t in cm.chat_session.tools}

    assert "query" in names(with_search)
    assert "query" not in names(without), names(without)
    assert {"plan", "tactic"} <= names(without)


def test_the_initial_prompt_carries_the_goal_and_the_plan_slot(config, coq):
    """build_initial_prompt is what the model sees first; check its content."""
    cm = ContextManager(coq, api_key=config.llm.api_key)

    goals = coq.get_goal_str()
    hypotheses = coq.get_hypothesis()
    proof_tree = ProofTree()
    proof_tree.add_node(
        tactic="Proof.",
        goals_before=goals or "",
        goals_after=goals or "",
        hypotheses_before=hypotheses or "",
        hypotheses_after=hypotheses or "",
        step_number=1,
        subgoals_after=[],
    )

    prompt = cm.build_initial_prompt(proof_tree.get_proof_tree_string())

    assert prompt.strip(), "the initial prompt is empty"
    assert "## PROOF FILE CONTEXT:" in prompt
    assert "## CURRENT PROOF PLAN: None" in prompt
    # The trimmed file context has to reach the prompt, theorem included.
    assert "orb_true_l" in prompt, prompt[:500]
    assert "Require" in prompt


def test_a_proof_plan_replaces_the_empty_plan_slot(config, coq):
    cm = ContextManager(coq, api_key=config.llm.api_key, proof_plan="destruct the bool")

    prompt = cm.build_initial_prompt("")

    assert "## CURRENT PROOF PLAN:\ndestruct the bool" in prompt
    assert "## CURRENT PROOF PLAN: None" not in prompt
