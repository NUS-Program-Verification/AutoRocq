"""Utility functions for Coq text processing."""

import re
import difflib
import traceback
from enum import Enum

def extract_essential_proof_content(logger, proof_file_content):
    """Extract essential content from proof file: imports and definitions for terms used in the theorem."""
    try:
        lines = proof_file_content.split('\n')
        essential_content = []

        # Step 1: Parse all definitions and their dependencies
        all_definitions = {}  # name -> {'lines': [...], 'dependencies': set()}

        current_def = None
        current_def_lines = []
        in_comment = False

        for line in lines:
            line_stripped = line.strip()

            # Track multi-line comment state
            # Check if we're entering or exiting a comment block
            if '(*' in line_stripped and '*)' in line_stripped:
                # Single-line comment or inline comment - remove it
                line_stripped = re.sub(r'\(\*.*?\*\)', '', line_stripped).strip()
                if not line_stripped:
                    continue
            elif '(*' in line_stripped:
                # Start of multi-line comment
                in_comment = True
                # Remove everything after (* on this line
                line_stripped = line_stripped[:line_stripped.index('(*')].strip()
                if not line_stripped:
                    continue
            elif '*)' in line_stripped:
                # End of multi-line comment
                in_comment = False
                # Remove everything before and including *)
                line_stripped = line_stripped[line_stripped.index('*)')+2:].strip()
                if not line_stripped:
                    continue
            elif in_comment:
                # Inside a multi-line comment - skip this line
                continue
            
            # Start of a new definition
            if line_stripped.startswith(('Definition ', 'Parameter ', 'Axiom ')):

                # Save previous definition if exists
                if current_def and current_def_lines:
                    deps = extract_dependencies_from_lines(current_def_lines)
                    all_definitions[current_def] = {
                        'lines': current_def_lines[:],
                        'dependencies': deps
                    }

                # Start new definition
                parts = line_stripped.split()
                if len(parts) >= 2:
                    current_def = parts[1].rstrip(':')
                    current_def_lines = [line]

                    # Check if definition ends on same line
                    if line_stripped.endswith('.'):
                        deps = extract_dependencies_from_lines(current_def_lines)
                        all_definitions[current_def] = {
                            'lines': current_def_lines[:],
                            'dependencies': deps
                        }
                        current_def = None
                        current_def_lines = []
                else:
                    current_def = None
                    current_def_lines = []

            elif current_def:
                # Continue collecting lines for current definition
                current_def_lines.append(line)

                # Check if definition is complete
                if line_stripped.endswith('.'):
                    deps = extract_dependencies_from_lines(current_def_lines)
                    all_definitions[current_def] = {
                        'lines': current_def_lines[:],
                        'dependencies': deps
                    }
                    current_def = None
                    current_def_lines = []

        # Step 2: Find the theorem and extract its direct dependencies
        theorem_found = False
        theorem_dependencies = set()

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith(('Theorem ', 'Lemma ')):
                theorem_found = True
                # Collect the complete theorem statement
                theorem_lines = []
                j = i
                while j < len(lines):
                    theorem_lines.append(lines[j])
                    if lines[j].strip().endswith('.') and 'Proof' not in lines[j]:
                        break
                    j += 1

                theorem_dependencies = extract_dependencies_from_lines(theorem_lines)
                break
            
        if not theorem_found:
            return "## Essential proof context:\n(current theorem not found)\n"

        # Step 3: Find all transitive dependencies using dependency graph
        needed_definitions = find_transitive_dependencies(theorem_dependencies, all_definitions)

        logger.debug(f"All available definitions: {list(all_definitions.keys())}")
        logger.debug(f"Required definitions: {needed_definitions}")
        
        missing_definitions = theorem_dependencies - needed_definitions
        if len(missing_definitions) > 0:
            logger.warning(f"Missing definitions for theorem: {list(missing_definitions)}")

        # Step 4: Extract imports
        imports = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith('Require ') and not line_stripped.startswith('(*'):
                clean_line = re.sub(r'\(\*.*?\*\)', '', line_stripped).strip()
                if clean_line:
                    imports.append(clean_line)

        # Add imports
        if imports:
            essential_content.extend(imports)
            essential_content.append("")

        # Add only the needed definitions in dependency order
        added_definitions = set()
        for def_name in needed_definitions:
            if def_name in all_definitions and def_name not in added_definitions:
                essential_content.extend(all_definitions[def_name]['lines'])
                essential_content.append("")
                added_definitions.add(def_name)

        # Add the theorem and proof
        essential_content.append("")
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith('Theorem ') or line_stripped.startswith('Lemma '):
                remaining_lines = lines[i:]
                clean_remaining = []
                in_comment = False
                for line in remaining_lines:
                    line_stripped = line.strip()
                    
                    # Track and remove comments
                    if '(*' in line_stripped and '*)' in line_stripped:
                        # Single-line comment - remove it
                        clean_line = re.sub(r'\(\*.*?\*\)', '', line).rstrip()
                        if clean_line:
                            clean_remaining.append(clean_line)
                    elif '(*' in line_stripped:
                        # Start of multi-line comment
                        in_comment = True
                        clean_line = line[:line.index('(*')].rstrip()
                        if clean_line:
                            clean_remaining.append(clean_line)
                    elif '*)' in line_stripped:
                        # End of multi-line comment
                        in_comment = False
                        clean_line = line[line.index('*)')+2:].rstrip()
                        if clean_line:
                            clean_remaining.append(clean_line)
                    elif not in_comment:
                        # Not in a comment - keep the line
                        clean_remaining.append(line.rstrip())
                
                essential_content.extend(clean_remaining)
                break
            
        result = '\n'.join(essential_content)
        result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)

        logger.info(f"Extracted essential content: {len(result)} chars")
        logger.info(f"Found {len(imports)} imports, {len(added_definitions)} definitions")

        return result

    except Exception as e:
        logger.error(f"Error extracting essential content: {e}")
        traceback.print_exc()
        return f"## Essential proof context:\nError extracting content: {e}\n"

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


# Coq built-in identifiers to filter out when extracting dependencies
COQ_BUILTINS = {
    'forall', 'fun', 'Prop', 'Type', 'Z', 'Numbers', 'BinNums', 'Datatypes',
    'true', 'false', 'Init', 'Reals', 'Rdefinitions', 'R', 'ZArith', 'BinInt',
    'Theorem', 'Lemma', 'Definition', 'Parameter', 'Axiom', 'Proof', 'Qed',
    'let', 'in', 'match', 'with', 'end', 'if', 'then', 'else', 'nat', 'bool',
    'list', 'option', 'unit', 'eq', 'and', 'or', 'not', 'exists', 'auto',
    'intros', 'apply', 'exact', 'assumption', 'constructor', 'destruct',
    'induction', 'simpl', 'unfold', 'fold', 'reflexivity', 'symmetry',
    'transitivity', 'rewrite', 'replace', 'assert', 'cut', 'generalize',
    'clear', 'clearbody', 'move', 'rename', 'pose', 'set', 'remember',
    'BuiltIn', 'IZR', 'WhyType', 'quot', 'rem', 'abs', 'le', 'lt', 'ge', 'gt'
}


def extract_dependencies_from_lines(lines: list) -> set:
    """
    Extract identifiers that could be dependencies from a list of lines.
    
    Args:
        lines: List of code lines to analyze
        
    Returns:
        Set of identifier names that are likely custom definitions
    """
    dependencies = set()

    # Join all lines and extract identifiers
    content = ' '.join(lines)

    # Remove Coq syntax and extract custom identifiers
    # Pattern to match identifiers that are likely custom definitions
    identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', content)

    for identifier in identifiers:
        if (identifier not in COQ_BUILTINS and
            not identifier.startswith('_') and
            len(identifier) > 1 and
            not identifier.isdigit() and
            not identifier[0].isupper() or identifier.startswith('is_') or identifier.startswith('to_')):
            dependencies.add(identifier)

    return dependencies


def find_transitive_dependencies(root_dependencies, all_definitions):
    """Find all transitive dependencies starting from root dependencies."""
    needed = set()
    to_process = list(root_dependencies)
    processed = set()

    while to_process:
        current = to_process.pop(0)

        if current in processed:
            continue

        processed.add(current)

        # If this dependency has a definition, include it and its dependencies
        if current in all_definitions:
            needed.add(current)
            # Add dependencies of this definition to processing queue
            for dep in all_definitions[current]['dependencies']:
                if dep not in processed:
                    to_process.append(dep)

    return needed


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