"""Utility functions for Coq text processing."""

import re
import difflib
from collections import deque
from enum import Enum
from pathlib import Path


def _same_file(left, right):
    """Compare source paths without requiring either path to still exist."""
    if not left or not right:
        return False
    return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)


def _referenced_terms(file_context, step):
    """Resolve global identifiers in a parsed Rocq sentence to CoqPyt terms."""
    stack = file_context.expr(step)[:0:-1]
    referenced = []

    while stack:
        element = stack.pop()
        if file_context.is_id(element):
            identifier = file_context.get_id(element)
            term = file_context.get_term(identifier) if identifier else None
            if term is not None and term not in referenced:
                referenced.append(term)
        elif file_context.is_notation(element):
            # Notation arguments can contain global references.
            stack.append(element[1:])
        elif isinstance(element, list):
            stack.extend(
                value for value in reversed(element) if isinstance(value, (dict, list))
            )
        elif isinstance(element, dict):
            stack.extend(
                value
                for value in reversed(element.values())
                if isinstance(value, (dict, list))
            )

    return referenced


def _structured_dependencies(proof, file_context, file_path):
    """Return local declarations needed by a proof in stable source order."""
    needed = {}
    pending = deque(proof.context)

    while pending:
        term = pending.popleft()
        step = getattr(term, "step", None)
        if step is None or not _same_file(getattr(term, "file_path", None), file_path):
            continue

        # An inductive type and its constructors share one declaration Step.
        step_key = id(step)
        if step_key in needed or step is getattr(proof, "step", None):
            continue

        needed[step_key] = term
        pending.extend(_referenced_terms(file_context, step))

    def source_position(term):
        start = term.step.ast.range.start
        return start.line, start.character

    return sorted(needed.values(), key=source_position)


def _source_sentence(lines, step):
    """Slice an end-exclusive LSP range, whose columns count UTF-16 units."""
    start, end = step.ast.range.start, step.ast.range.end
    if not (0 <= start.line <= end.line < len(lines)) or (
        start.line, start.character
    ) >= (end.line, end.character):
        raise ValueError("Invalid CoqPyt source range")

    def column(position):
        encoded = lines[position.line].encode("utf-16-le")
        if not 0 <= position.character * 2 <= len(encoded):
            raise ValueError("CoqPyt source column is outside the source line")
        return len(encoded[:position.character * 2].decode("utf-16-le"))

    first, last = column(start), column(end)
    if not lines[start.line][:first].strip():
        first = 0
    if start.line == end.line:
        return lines[start.line][first:last]
    return "\n".join([
        lines[start.line][first:],
        *lines[start.line + 1:end.line],
        lines[end.line][:last],
    ])


def extract_essential_proof_content(
    logger,
    proof_file_content,
    *,
    proof=None,
    file_context=None,
    file_path=None,
):
    """Extract imports and dependencies from the current parsed Rocq proof."""
    missing = [
        name for name, value in (
            ("proof", proof), ("file_context", file_context), ("file_path", file_path)
        ) if value is None
    ]
    if missing:
        message = f"CoqPyt proof context unavailable: {', '.join(missing)} missing"
        logger.error(message)
        raise ValueError(message)

    try:
        lines = proof_file_content.split("\n")
        declarations = _structured_dependencies(proof, file_context, file_path)
        imports = []
        for line in proof_file_content.splitlines():
            statement = line.partition("(*")[0].strip()
            words = statement.split()
            if (
                statement.startswith(("Require ", "Open Scope "))
                or (words[:1] == ["From"] and "Require" in words)
            ):
                imports.append(statement)

        parts = [*imports, *(_source_sentence(lines, term.step) for term in declarations), _source_sentence(lines, proof.step), *(_source_sentence(lines, step.step) for step in proof.steps)]
        return "\n\n".join(parts)
    except Exception as error:
        message = f"CoqPyt proof context extraction failed: {error}"
        logger.error(message)
        raise RuntimeError(message) from error


def extract_search_terms(text: str) -> str:
    """
    Extract relevant search terms from Coq goals or error messages.
    
    Args:
        text: Coq goals string or error message
        
    Returns:
        Space-separated search terms for querying
    """
    if not text:
        return "arithmetic lemma"
    
    try:
        # Extract mathematical operators and concepts
        math_terms = re.findall(
            r'\b(?:forall|exists|int|nat|bool|Z|R|le|lt|ge|gt|eq|mul|add|sub|div|mod|sqrt|abs)\b',
            text,
            re.IGNORECASE
        )
        
        # Extract function/predicate names (capitalized words)
        predicates = re.findall(r'\b[A-Z][a-zA-Z_0-9]*\b', text)
        
        # Extract numeric patterns
        numbers = re.findall(r'\b\d+\b', text)
        
        # Combine and deduplicate
        all_terms = list(set(math_terms + predicates + numbers[:3]))  # Limit numbers
        
        # Create search query
        if all_terms:
            return " ".join(all_terms[:5])  # Limit to 5 terms
        else:
            # Fallback: use first few words
            words = text.split()[:10]
            return " ".join(word.strip('(),:->') for word in words if len(word) > 2)
            
    except Exception:
        return "arithmetic lemma"  # Fallback


class CoqError(Enum):
    """Enum representing different types of Coq errors."""
    syntax = "syntax_error"
    typing = "type_error"
    unbound = "unbound_error"
    apply = "application_error"
    convert = "convertible_error"
    premise = "premise_error"
    goal = "goal_error"
    unify = "unification_error"
    timeout = "timeout"
    unknown = "other_error"

def classify_error_type(error_message: str) -> CoqError:
    """Classify error type from error message."""
    if not error_message:
        return CoqError.unknown
    
    error_lower = error_message.lower()
    
    if "syntax error" in error_lower or "parse error" in error_lower:
        return CoqError.syntax
    elif "type" in error_lower and ("mismatch" in error_lower or "error" in error_lower):
        return CoqError.typing
    elif "not found" in error_lower or "unbound" in error_lower:
        return CoqError.unbound
    elif "no applicable tactic" in error_lower or "unable to apply" in error_lower:
        return CoqError.apply
    elif "convertible" in error_lower:
        return CoqError.convert
    elif "the current goal" in error_lower:
        return CoqError.goal
    elif "unable to unify" in error_lower:
        return CoqError.unify
    elif "premises" in error_lower:
        return CoqError.premise
    elif "timeout" in error_lower:
        return CoqError.timeout
    else:
        return CoqError.unknown


def hints_from_error(tactic: str, error: str) -> str:
    """
    Provide hints based on keywords in a Coq error message.
    
    Args:
        error: Coq error message
        
    Returns:
        Hint string to help resolve the error
    """
    if not error:
        return ""
    
    type_check_hint = "You may consider using 'query' tool to 'Check' the types or 'Print' definitions."

    try:
        error_type: CoqError = classify_error_type(error)
        
        if error_type is CoqError.syntax:
            return "The syntax of the tactic is incorrect. Please review the tactic and try again."
        
        elif error_type is CoqError.unbound:
            search_terms = extract_search_terms(tactic)
            return f"You may consider using 'query' tool to 'Search' for relevant lemmas about: {search_terms}"
        
        elif error_type is CoqError.convert:
            return "Coq cannot establish that two terms are definitionally equal. You may consider rewriting or simplifying the terms."
        
        elif error_type is CoqError.goal:
            return "Please review the current goal carefully."
        
        elif error_type is CoqError.unify:
            return "This happens because the two expressions have incompatible types. " + type_check_hint
        
        elif error_type is CoqError.typing:
            return type_check_hint
        
        elif error_type is CoqError.apply:
            return "The tactic you tried doesn't apply to the current goal or context. " + type_check_hint
        
        elif error_type is CoqError.premise:
            return (
                "You do not provide values for all premises of the lemma/theorem. You may consider\n"
                "(1) providing 'tactic' with explicit values, e.g. 'apply (theorem arg1 arg2 ... argN)' or 'apply theorem with (x := value)',\n"
                "(2) using 'query' tool to 'Check' the types or 'Print' definitions,\n"
                "(3) using 'eapply' instead of 'apply' for more flexible application."
            )
        
        else:
            return ""
            
    except Exception:
        return ""


def extract_goal_pattern(goals: str) -> str:
    """Enhanced pattern extraction with better goal structure understanding."""
    try:
        if not goals:
            return ""
        
        goals_clean = goals.lower().strip()
        patterns = []
        
        # Mathematical operators and relations
        if '=' in goals_clean:
            patterns.append('equality')
        if '<=' in goals_clean or '>=' in goals_clean:
            patterns.append('inequality')  
        if '<' in goals_clean and '<=' not in goals_clean:
            patterns.append('less_than')
        if '>' in goals_clean and '>=' not in goals_clean:
            patterns.append('greater_than')
        
        # Logical operators
        if '∀' in goals_clean or 'forall' in goals_clean:
            patterns.append('forall')
        if '∃' in goals_clean or 'exists' in goals_clean:
            patterns.append('exists')
        if '∧' in goals_clean or '/\\' in goals_clean:
            patterns.append('and')
        if '∨' in goals_clean or '\\/' in goals_clean:
            patterns.append('or')
        if '->' in goals_clean or '→' in goals_clean:
            patterns.append('implies')
        if '~' in goals_clean or '¬' in goals_clean:
            patterns.append('not')
        
        # Data types
        if 'int' in goals_clean:
            patterns.append('int')
        if 'nat' in goals_clean:
            patterns.append('nat')
        if 'bool' in goals_clean:
            patterns.append('bool')
        if 'list' in goals_clean:
            patterns.append('list')
        if 'string' in goals_clean:
            patterns.append('string')
        
        # Mathematical operations
        if '+' in goals_clean:
            patterns.append('plus')
        if '*' in goals_clean:
            patterns.append('mult')
        if '-' in goals_clean:
            patterns.append('minus')
        if '/' in goals_clean:
            patterns.append('div')
        if 'abs' in goals_clean:
            patterns.append('abs')
        
        # Common predicates and functions
        if 'length' in goals_clean:
            patterns.append('length')
        if 'sint32' in goals_clean or 'is_sint32' in goals_clean:
            patterns.append('sint32')
        
        # Goal structure indicators
        if '|-' in goals_clean:
            patterns.append('has_hypothesis')
        if 'goal' in goals_clean.lower():
            patterns.append('structured_goal')
        
        # Count approximate complexity
        goal_lines = [line for line in goals_clean.split('\n') if line.strip() and not line.startswith('-')]
        if len(goal_lines) > 5:
            patterns.append('complex')
        elif len(goal_lines) > 2:
            patterns.append('moderate')
        else:
            patterns.append('simple')
        
        return ','.join(sorted(patterns)) if patterns else goals_clean[:50]
        
    except Exception as e:
        return goals_clean


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate textual similarity between two strings using simple word overlap."""
    try:
        if not text1 or not text2:
            return 0.0
        
        if text1.strip() == text2.strip():
            return 1.0
        
        # Normalize texts
        text1_clean = text1.lower().strip()
        text2_clean = text2.lower().strip()
        
        # Extract words (split by whitespace and common separators)
        words1 = set(re.findall(r'\b\w+\b', text1_clean))
        words2 = set(re.findall(r'\b\w+\b', text2_clean))
        
        # Filter out very common words that don't add meaning
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        words1 = words1 - common_words
        words2 = words2 - common_words
        
        if not words1 and not words2:
            return 0.0
        
        if not words1 or not words2:
            return 0.0
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
        
    except Exception as e:
        return 0.0


def calculate_similarity(pattern1: str, pattern2: str) -> float:
    """Calculate similarity between two goal patterns."""
    try:
        if not pattern1 or not pattern2:
            return 0.0
        
        if pattern1 == pattern2:
            return 1.0
        
        # Split patterns into components
        components1 = set(pattern1.split(',')) if ',' in pattern1 else {pattern1}
        components2 = set(pattern2.split(',')) if ',' in pattern2 else {pattern2}
        
        # Calculate Jaccard similarity
        intersection = len(components1.intersection(components2))
        union = len(components1.union(components2))
        
        return intersection / union if union > 0 else 0.0
        
    except Exception as e:
        return calculate_text_similarity(pattern1, pattern2)


def count_goals(goals_str: str) -> int:
    """Count the number of goals in a goal string."""
    try:
        if not goals_str or goals_str.strip() in ["", "(no current goal)", "No more goals"]:
            return 0
        
        # Simple heuristic: count lines that look like goals
        lines = goals_str.split('\n')
        goal_count = 0
        
        for line in lines:
            line = line.strip()
            # Skip empty lines and separators
            if not line or line.startswith('=') or line.startswith('-'):
                continue
            # Count lines that end with goal-like patterns
            if ':' in line or line.endswith('=') or any(op in line for op in ['∀', '∃', '→', '∧', '∨']):
                goal_count += 1
        
        return max(1, goal_count)  # At least 1 if we have any content
        
    except Exception as e:
        return 0


def goal_diff(goal1: str, goal2: str) -> str:
    """Generate a unified textual diff between two Coq goal strings."""
    try:
        if not goal1 or not goal2:
            return ""

        if goal1.strip() == goal2.strip():
            return ""

        lines1 = goal1.splitlines(keepends=True)
        lines2 = goal2.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines1, lines2,
            fromfile="goal_before", tofile="goal_after",
            lineterm=""
        )
        diff_str = "\n".join(diff)
        return diff_str if len(diff_str) <= len(goal2) else goal2

    except Exception as e:
        return ""
