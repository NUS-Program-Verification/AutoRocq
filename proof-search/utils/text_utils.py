import re
import difflib


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


def goal_diff(goal1: str, goal2: str) -> str:
    """Generate a unified textual diff between two goal strings."""
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
