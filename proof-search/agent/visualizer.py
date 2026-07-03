"""
Central visualization module.

Renders proof state, proof tree, and agent reasoning trace for the terminal.
Also provides JSON-serializable dicts for programmatic access (IDE / web UI).

Both interactive and autonomous modes use this module.
Output from this module is always printed to stdout for usability. 
Internal logging (through utils.logger) and LLM conversation does not go through this module.
"""

import re
from typing import Any, Dict, List, Optional

try:
    import rich  # noqa: F401
    _RICH = True
except ImportError:
    _RICH = False


# ---------------------------------------------------------------------------
# Public API: structured data (JSON-serializable)
# ---------------------------------------------------------------------------

def format_goals(goals_str: str, hyps_str: str = "") -> Dict[str, Any]:
    """
    Parse a Rocq proof-state string into a structured dict.

    Returns::
        {
            "focused_goal":    str,
            "background_goals": [str, ...],
            "hypotheses":      [str, ...],
        }
    """
    hypotheses: List[str] = [
        ln.strip() for ln in (hyps_str or "").splitlines() if ln.strip()
    ]

    if not (goals_str and goals_str.strip()):
        return {"focused_goal": "", "background_goals": [], "hypotheses": hypotheses}

    text = goals_str.strip()

    if text.startswith("Goals:"):
        text = text[6:].strip()

    if "\nBullet:" in text:
        text = text.split("\nBullet:")[0].strip()

    focused_text, _, bg_raw = text.partition("\nStack:")
    focused_text = focused_text.strip()
    background_goals: List[str] = [
        ln.strip() for ln in bg_raw.splitlines() if ln.strip()
    ]

    dash_parts = re.split(r"\n-{5,}\n", focused_text)
    if len(dash_parts) >= 2:
        goal_section = dash_parts[1].strip()
        lines = goal_section.splitlines()
        conclusion_lines: List[str] = []
        in_conclusion = not any(": " in ln for ln in lines)
        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                in_conclusion = True
            elif in_conclusion or ": " not in stripped:
                conclusion_lines.append(stripped)
            elif not hypotheses:
                hypotheses.append(stripped)
        focused_goal = "\n".join(conclusion_lines).strip() or goal_section
    else:
        focused_goal = focused_text

    return {
        "focused_goal": focused_goal,
        "background_goals": background_goals,
        "hypotheses": hypotheses,
    }


def explain(context_manager) -> Dict[str, Any]:
    """
    Return the most recent agent action as a JSON-serializable dict.

    Keys::
        plan_rationale      — current proof plan text (str)
        last_action_type    — "plan" | "tactic" | "query" | "rollback" | None
        last_action_content — raw content of the action (str | dict | None)
        last_query          — query string if last action was a query (str | None)
        last_query_result   — query result text (str | None)
    """
    chat = context_manager.chat_session
    result: Dict[str, Any] = {
        "plan_rationale": chat.current_plan or "",
        "last_action_type": None,
        "last_action_content": None,
        "last_query": None,
        "last_query_result": None,
    }
    info: Optional[Dict] = getattr(context_manager, "last_action_info", None)
    if info:
        result["last_action_type"] = info.get("type")
        result["last_action_content"] = info.get("content")
        result["last_query"] = info.get("query")
        result["last_query_result"] = info.get("query_result")
    return result


# ---------------------------------------------------------------------------
# Public API: terminal rendering (str)
# ---------------------------------------------------------------------------

def render_state(goals_str: str, title: str = "Proof State") -> str:
    """
    Return a formatted, boxed terminal string for the current proof state.
    """
    body = _clean_goals_str(goals_str)
    return _rich_box(body, title) if _RICH else _plain_box(body, title)


def _clean_goals_str(goals_str: str) -> str:
    """Strip noise from CoqPyt's get_goal_str() without dropping any content."""
    if not goals_str or not goals_str.strip():
        return "No current goals."
    text = goals_str.strip()
    # Remove "Bullet: ..." trailers from CoqPyt
    text = re.sub(r"\nBullet:.*$", "", text, flags=re.MULTILINE).strip()
    return text or "No current goals."


def render_tree(proof_tree, title: str = "Proof Tree") -> str:
    """Return a formatted, boxed proof-tree string."""
    tree_text = proof_tree.render() if proof_tree is not None else "No proof tree available."
    return _rich_box(tree_text, title) if _RICH else _plain_box(tree_text, title)


def render_explain(context_manager, title: str = "Agent Reasoning") -> str:
    """Return a formatted, boxed string for the agent reasoning trace."""
    data = explain(context_manager)
    body = _format_explain_body(data)
    return _rich_box(body, title) if _RICH else _plain_box(body, title)


def render_action(action_type: str, content: Any, success: bool = True) -> str:
    """Return a short formatted line (or panel) for an agent action."""
    return _rich_action(action_type, content, success) if _RICH else _plain_action(action_type, content, success)


# ---------------------------------------------------------------------------
# Explain body formatter
# ---------------------------------------------------------------------------

def _format_explain_body(data: Dict[str, Any]) -> str:
    lines: List[str] = []

    plan = data.get("plan_rationale") or ""
    if plan:
        lines.append("Plan:")
        lines.extend(f"  {ln}" for ln in plan.splitlines())
    else:
        lines.append("Plan: (none)")

    lines.append("")

    action_type = data.get("last_action_type")
    action_content = data.get("last_action_content")
    if action_type:
        lines.append(f"Last action: {action_type}")
        if action_content:
            content_str = (
                str(action_content)
                if not isinstance(action_content, dict)
                else f"reason={action_content.get('reason', '')}  steps={action_content.get('steps', 1)}"
            )
            lines.append(f"  {content_str}")
    else:
        lines.append("Last action: (none)")

    query = data.get("last_query")
    if query:
        lines.append("")
        lines.append(f"Last query: {query}")
        result = data.get("last_query_result") or ""
        if result:
            result_lines = result.splitlines()
            lines.append("Result (first 5 lines):")
            lines.extend(f"  {ln}" for ln in result_lines[:5])
            if len(result_lines) > 5:
                lines.append(f"  … ({len(result_lines) - 5} more lines)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plain-text renderers
# ---------------------------------------------------------------------------

def _plain_box(body: str, title: str) -> str:
    """Wrap body text in a plain-text box with a title header."""
    sep = "=" * 52
    lines = [sep, f"  {title}", sep]
    lines.extend(body.splitlines())
    lines.append(sep)
    return "\n".join(lines)

def _plain_action(action_type: str, content: Any, success: bool) -> str:
    icon = "✓" if success else "✗"
    if action_type == "plan":
        return _plain_box(str(content), "Plan")
    if action_type == "tactic":
        return f"[TACTIC {icon}] {content}"
    if action_type == "query":
        return f"[QUERY] {content}"
    if action_type == "rollback":
        reason = content.get("reason", "") if isinstance(content, dict) else str(content)
        steps = content.get("steps", 1) if isinstance(content, dict) else 1
        return f"[ROLLBACK ×{steps}] {reason}"
    return f"[{action_type.upper()}] {content}"


# ---------------------------------------------------------------------------
# Rich renderers
# ---------------------------------------------------------------------------

def _rich_box(body: str, title: str) -> str:
    from io import StringIO
    from rich.console import Console as _Console
    from rich.panel import Panel as _Panel

    buf = StringIO()
    c = _Console(file=buf, highlight=False, markup=False)
    c.print(_Panel(body, title=title, expand=False))
    return buf.getvalue()

def _rich_action(action_type: str, content: Any, success: bool) -> str:
    from io import StringIO
    from rich.console import Console as _Console
    from rich.panel import Panel as _Panel

    buf = StringIO()
    c = _Console(file=buf, highlight=False, markup=True)

    if action_type == "plan":
        c.print(_Panel(str(content), title="[bold blue]Plan[/bold blue]", expand=False))
    elif action_type == "tactic":
        color = "green" if success else "red"
        icon = "✓" if success else "✗"
        c.print(f"  [{color}][{icon} Tactic][/{color}] [bold]{content}[/bold]")
    elif action_type == "query":
        c.print(f"  [cyan][? Query][/cyan] {content}")
    elif action_type == "rollback":
        reason = content.get("reason", "") if isinstance(content, dict) else str(content)
        steps = content.get("steps", 1) if isinstance(content, dict) else 1
        c.print(f"  [yellow][↩ Rollback ×{steps}][/yellow] {reason}")
    else:
        c.print(f"  [{action_type.upper()}] {content}")

    return buf.getvalue()
