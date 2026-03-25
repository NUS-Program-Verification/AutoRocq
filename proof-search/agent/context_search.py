"""
Context Search Module for Proof Agent

Provides Coq Command Search: Uses Coq's built-in Search/Print/Check/About/Locate/Print Assumptions commands
with adaptive result size management.
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from utils.logger import setup_logger


@dataclass
class SearchResult:
    """Represents a search result with relevance score."""
    content: str
    source: str  # 'coq_command'
    relevance_score: float
    metadata: Dict[str, Any] = None
    result_size: int = 0
    original_size: int = 0  # Track original size before reduction
    reduction_applied: str = None  # Track what reduction was applied


class ResultReducer:
    """Handles adaptive reduction of large search results."""
    
    def __init__(self):
        self.max_small_result = 500       # Keep full results under 500 chars
        self.max_medium_result = 1000     # Boundary-aware truncation for 500-1K
        self.max_large_result = 1000      # Heavy reduction for >1K
        self.max_entries = 10             # Max entries in summaries
        self.result_hit_count = {}        # Count of results hit {hash: count}

        # Setup logger
        self.logger = setup_logger("ResultReducer")
        
    def reduce_result(self, content: str, query_type: str, goal_context: str = "") -> Tuple[str, str]:
        """
        Apply contextual reduction strategy based on content size and type.
        
        Returns:
            Tuple of (reduced_content, reduction_method_used)
        """
        if not content:
            return content, "none"
        
        original_size = len(content)
        
        # Strategy 1: Small results - keep as-is
        if original_size <= self.max_small_result:
            return content, "none"
        
        # Strategy 2: Medium results - boundary-aware truncation
        elif original_size <= self.max_medium_result:
            if query_type in ['direct_search', 'search_lemma', 'search_pattern']:
                return self._boundary_aware_truncation(content, self.max_medium_result), "boundary_aware_truncation"
            else:
                return content[:self.max_medium_result] + "\n... (truncated)", "simple_truncation"
        
        # Strategy 3: Large results - aggressive reduction
        else:
            if query_type in ['direct_search', 'search_lemma', 'search_pattern']:
                return self._structured_summarization(content, goal_context), "structured_summary"
            else:
                return self._boundary_aware_truncation(content, self.max_large_result), "boundary_aware_truncation"
    
    def _boundary_aware_truncation(self, content: str, max_size: int) -> str:
        """Truncate at theorem boundaries to keep complete entries."""
        if len(content) <= max_size:
            return content
        
        # Try to truncate at theorem/lemma boundaries
        lines = content.split('\n')
        result_lines = []
        current_size = 0
        
        for line in lines:
            if current_size + len(line) + 1 > max_size:
                # Check if we're in the middle of a theorem
                if any(keyword in line.lower() for keyword in ['theorem', 'lemma', 'definition', 'axiom']):
                    # Don't start a new theorem if we're out of space
                    break
                # Otherwise, take partial line if it's a continuation
                remaining_space = max_size - current_size
                if remaining_space > 50:  # Only if we have meaningful space
                    result_lines.append(line[:remaining_space] + "...")
                break
            
            result_lines.append(line)
            current_size += len(line) + 1
        
        result = '\n'.join(result_lines)
        if len(result) < len(content):
            result += "\n... (showing first complete entries)"
        
        return result
    
    def _structured_summarization(self, content: str, goal_context: str = "") -> str:
        """Create a structured summary of search results."""
        lines = content.split('\n')
        
        # Extract theorem/lemma names and signatures
        entries = self._parse_search_entries(lines)
        
        if not entries:
            # Fallback to boundary-aware truncation if parsing fails
            return self._boundary_aware_truncation(content, self.max_large_result)
        
        # Filter and rank entries based on relevance
        ranked_entries = self._rank_entries(entries, goal_context)
        
        # Create summary
        summary_parts = []
        summary_parts.append(f"SEARCH RESULTS SUMMARY ({len(entries)} total found, showing top {min(len(ranked_entries), self.max_entries)}):")
        summary_parts.append("")
        
        # Show top entries with their signatures
        for i, entry in enumerate(ranked_entries[:self.max_entries]):
            
            # Update result hit count for this entry
            result_hash = hash(frozenset(entry.items()))
            self.result_hit_count[result_hash] = self.result_hit_count.get(result_hash, 0) + 1
            
            name = entry.get('name', 'Unknown')
            signature = entry.get('signature', '')
            module = entry.get('module', '')
            
            entry_line = f"{i+1}. {name}"
            if module:
                entry_line += f" (from {module})"
            if signature:
                entry_line += f": {signature}"
            
            summary_parts.append(entry_line)
        
        # Add statistics
        if len(entries) > self.max_entries:
            summary_parts.append("")
            summary_parts.append(f"... and {len(entries) - self.max_entries} more entries")
        
        # Add categorization if possible
        categories = self._categorize_entries(ranked_entries[:self.max_entries])
        if len(categories) > 1:
            summary_parts.append("")
            summary_parts.append("Categories found:")
            for category, count in categories.items():
                summary_parts.append(f"  - {category}: {count} entries")
        
        return '\n'.join(summary_parts)
    
    def _parse_search_entries(self, lines: List[str]) -> List[Dict[str, str]]:
        """Parse search result lines into structured entries."""
        entries = []
        current_entry = {}
        
        for line in lines:
            # Check if line is indented BEFORE stripping (indented lines are continuations)
            is_indented = line.startswith(' ') or line.startswith('\t')
            line_stripped = line.strip()
            
            if not line_stripped:
                if current_entry:
                    entries.append(current_entry)
                    current_entry = {}
                continue
            
            # Try to identify theorem/lemma declarations
            # Common patterns: "name: signature" or "Module.name: signature"
            # Only lines that are NOT indented and contain ':' start a new entry
            if ':' in line_stripped and not is_indented:
                # This looks like a new entry
                if current_entry:
                    entries.append(current_entry)
                
                parts = line_stripped.split(':', 1)
                name_part = parts[0].strip()
                signature_part = parts[1].strip() if len(parts) > 1 else ""
                
                # Extract module if present
                module = ""
                if '.' in name_part:
                    name_parts = name_part.split('.')
                    if len(name_parts) > 1:
                        module = '.'.join(name_parts[:-1])
                        name = name_parts[-1]
                    else:
                        name = name_part
                else:
                    name = name_part
                
                current_entry = {
                    'name': name,
                    'full_name': name_part,
                    'signature': signature_part,
                    'module': module,
                    'raw_line': line_stripped
                }
            else:
                # Continuation of current entry (indented lines or lines without ':')
                if current_entry:
                    current_entry['signature'] = current_entry.get('signature', '') + ' ' + line_stripped
        
        # Don't forget the last entry
        if current_entry:
            entries.append(current_entry)
        
        return entries
    
    def _rank_entries(self, entries: List[Dict[str, str]], goal_context: str) -> List[Dict[str, str]]:
        """Rank entries by relevance to the goal context."""
        if not goal_context:
            return entries  # No ranking possible without context
        
        # Extract keywords from goal context
        goal_keywords = self._extract_keywords(goal_context.lower())
        
        scored_entries = []
        for entry in entries:
            score = 0
            name = entry.get('name', '').lower()
            signature = entry.get('signature', '').lower()
            module = entry.get('module', '').lower()
            
            # Score based on keyword matches
            for keyword in goal_keywords:
                if keyword in name:
                    score += 3  # Name matches are most important
                if keyword in signature:
                    score += 2  # Signature matches are good
                if keyword in module:
                    score += 1  # Module matches are less important
            
            # Prefer shorter, simpler names (likely more fundamental)
            if len(name) < 10:
                score += 1
            
            # Prefer standard library entries
            if module in ['Z', 'Nat', 'List', 'Bool', 'Arith']:
                score += 1
            
            # Apply hit count penalty (compute hash from entry name)
            import hashlib
            result_hash = hashlib.md5(name.encode()).hexdigest()
            hit_count = self.result_hit_count.get(result_hash, 0)
            if hit_count > 0:
                # exponential decay of frequently retrieved results
                score -= 2 ** (hit_count - 1)
            
            scored_entries.append((score, entry))
        
        # Sort by score (highest first), then by name length (shorter first)
        scored_entries.sort(key=lambda x: (-x[0], len(x[1].get('name', ''))))
        
        return [entry for score, entry in scored_entries]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from goal context."""
        # Remove common Coq syntax
        text = re.sub(r'[(){}[\],.]', ' ', text)
        
        # Split into words and filter
        words = text.split()
        keywords = []
        
        for word in words:
            # Skip very short words and common Coq keywords
            if len(word) < 3:
                continue
            if word in ['forall', 'exists', 'fun', 'let', 'match', 'with', 'end', 'then', 'else']:
                continue
            
            keywords.append(word)
        
        return list(set(keywords))  # Remove duplicates
    
    def _categorize_entries(self, entries: List[Dict[str, str]]) -> Dict[str, int]:
        """Categorize entries by their apparent type/purpose."""
        categories = {}
        
        for entry in entries:
            name = entry.get('name', '').lower()
            signature = entry.get('signature', '').lower()
            
            # Determine category based on name patterns
            if any(suffix in name for suffix in ['_eq', '_refl', '_sym', '_trans']):
                category = 'Equality'
            elif any(suffix in name for suffix in ['_le', '_lt', '_ge', '_gt']):
                category = 'Ordering'
            elif any(suffix in name for suffix in ['_add', '_mul', '_sub', '_div']):
                category = 'Arithmetic'
            elif any(suffix in name for suffix in ['_nonneg', '_pos', '_neg']):
                category = 'Sign/Positivity'
            elif 'abs' in name:
                category = 'Absolute Value'
            elif any(suffix in name for suffix in ['_spec', '_correct']):
                category = 'Specifications'
            else:
                category = 'General'
            
            categories[category] = categories.get(category, 0) + 1
        
        return categories


class CoqCommandSearch:
    """Handles Coq command-line search operations with adaptive result reduction."""
    
    def __init__(self, coq_interface):
        """
        Initialize with CoqInterface from backend.coq_interface.
        
        Args:
            coq_interface: Instance of CoqInterface from backend.coq_interface
        """
        self.coq = coq_interface
        self.reducer = ResultReducer()

        # Setup logger
        self.logger = setup_logger("CoqCommandSearch")
        
        # Ensure the CoqInterface is loaded
        if not hasattr(self.coq, 'proof_file') or self.coq.proof_file is None:
            self.logger.info("Loading CoqInterface...")
            try:
                self.coq.load()
                self.logger.info("✅ CoqInterface loaded successfully")
            except Exception as e:
                self.logger.error(f"❌ Failed to load CoqInterface: {e}")
    
    def _create_search_result(self, content: str, query: str, query_type: str, goal_context: str = "") -> SearchResult:
        """Create a SearchResult with adaptive size reduction."""
        original_size = len(content) if content else 0
        
        # Apply adaptive reduction
        reduced_content, reduction_method = self.reducer.reduce_result(content, query_type, goal_context)
        final_size = len(reduced_content) if reduced_content else 0
        
        # Log reduction if applied
        if reduction_method != "none":
            self.logger.info(f"Applied {reduction_method}: {original_size} → {final_size} chars ({original_size - final_size} saved)")
        
        return SearchResult(
            content=reduced_content,
            source='coq_command',
            relevance_score=1.0 if reduced_content and "No results found" not in reduced_content else 0.0,
            metadata={
                'query': query, 
                'type': query_type,
                'reduction_applied': reduction_method,
                'original_size': original_size,
                'size_saved': original_size - final_size
            },
            result_size=final_size,
            original_size=original_size,
            reduction_applied=reduction_method
        )
    
    def search_lemma(self, lemma_name: str, goal_context: str = "") -> SearchResult:
        """Search for a specific lemma or theorem."""
        query = f"Search {lemma_name}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'search_lemma', goal_context)
    
    def search_pattern(self, pattern: str, goal_context: str = "") -> SearchResult:
        """Search for theorems matching a pattern."""
        # Clean the pattern for Coq search
        if not pattern.startswith('(') and not pattern.endswith(')'):
            pattern = f"({pattern})"
        
        query = f"Search {pattern}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'search_pattern', goal_context)
    
    def print_definition(self, identifier: str) -> SearchResult:
        """Print the definition of an identifier."""
        query = f"Print {identifier}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'print_definition')
    
    def print_assumptions(self, identifier: str = None) -> SearchResult:
        """Print assumptions of an identifier or all assumptions."""
        if identifier:
            query = f"Print Assumptions {identifier}."
        else:
            query = "Print Assumptions."
        
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'print_assumptions')
    
    def locate_definition(self, identifier: str) -> SearchResult:
        """Locate the definition of an identifier."""
        query = f"Locate {identifier}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'locate_definition')
    
    def about_identifier(self, identifier: str) -> SearchResult:
        """Get information about an identifier."""
        query = f"About {identifier}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'about_identifier')
    
    def check_term(self, term: str) -> SearchResult:
        """Check the type of a term."""
        query = f"Check {term}."
        result = self.coq.search(query)
        return self._create_search_result(result, query, 'check_term')
    
    def auto_search(self, search_request: str, goal_context: str = "") -> SearchResult:
        """Automatically determine search type and execute with adaptive reduction."""
        search_request = search_request.strip()
        
        # All commands now go through the enhanced search() method
        result = self.coq.search(search_request)
        
        # Determine type from command
        cmd_type = search_request.split()[0].lower() if search_request else 'unknown'
        type_mapping = {
            'search': 'direct_search',
            'print': 'direct_print',
            'locate': 'direct_locate', 
            'about': 'direct_about',
            'check': 'direct_check'
        }

        query_type = type_mapping.get(cmd_type, 'auto_search')
        return self._create_search_result(result, search_request, query_type, goal_context)
    
    def execute_coq_query(self, query_type: str, identifier: str = None, pattern: str = None, goal_context: str = "") -> SearchResult:
        """Execute a Coq query by type with parameters and adaptive reduction."""
        try:
            if query_type.lower() == 'search':
                if pattern:
                    return self.search_pattern(pattern, goal_context)
                elif identifier:
                    return self.search_lemma(identifier, goal_context)
                else:
                    error_msg = "Search requires either identifier or pattern"
                    return SearchResult(
                        content=error_msg,
                        source='coq_command',
                        relevance_score=0.0,
                        metadata={'query_type': query_type, 'error': 'Missing parameters'},
                        result_size=len(error_msg)
                    )
            elif query_type.lower() == 'print':
                if identifier:
                    return self.print_definition(identifier)
                else:
                    error_msg = "Print requires identifier"
                    return SearchResult(
                        content=error_msg,
                        source='coq_command',
                        relevance_score=0.0,
                        metadata={'query_type': query_type, 'error': 'Missing identifier'},
                        result_size=len(error_msg)
                    )
            elif query_type.lower() == 'print_assumptions':
                return self.print_assumptions(identifier)
            elif query_type.lower() == 'locate':
                if identifier:
                    return self.locate_definition(identifier)
                else:
                    error_msg = "Locate requires identifier"
                    return SearchResult(
                        content=error_msg,
                        source='coq_command',
                        relevance_score=0.0,
                        metadata={'query_type': query_type, 'error': 'Missing identifier'},
                        result_size=len(error_msg)
                    )
            elif query_type.lower() == 'about':
                if identifier:
                    return self.about_identifier(identifier)
                else:
                    error_msg = "About requires identifier"
                    return SearchResult(
                        content=error_msg,
                        source='coq_command',
                        relevance_score=0.0,
                        metadata={'query_type': query_type, 'error': 'Missing identifier'},
                        result_size=len(error_msg)
                    )
            elif query_type.lower() == 'check':
                if identifier:
                    return self.check_term(identifier)
                else:
                    error_msg = "Check requires term"
                    return SearchResult(
                        content=error_msg,
                        source='coq_command',
                        relevance_score=0.0,
                        metadata={'query_type': query_type, 'error': 'Missing term'},
                        result_size=len(error_msg)
                    )
            else:
                error_msg = f"Unknown query type: {query_type}"
                return SearchResult(
                    content=error_msg,
                    source='coq_command',
                    relevance_score=0.0,
                    metadata={'query_type': query_type, 'error': 'Unknown query type'},
                    result_size=len(error_msg)
                )
        except Exception as e:
            error_msg = f"Error executing {query_type}: {str(e)}"
            return SearchResult(
                content=error_msg,
                source='coq_command',
                relevance_score=0.0,
                metadata={'query_type': query_type, 'error': str(e)},
                result_size=len(error_msg)
            )


class ContextSearch:
    """
    Simplified context search interface with adaptive result reduction.
    """
    
    def __init__(self, coq_interface, history_file: str = None):
        """
        Initialize context search with CoqInterface.
        
        Args:
            coq_interface: Instance of CoqInterface from backend.coq_interface
            history_file: Ignored (kept for backward compatibility)
        """
        self.coq_search = CoqCommandSearch(coq_interface)
        self.logger = setup_logger("ContextSearch")
    
    def search(self, query: str, goal_context: str = "") -> SearchResult:
        """
        Simplified search interface with adaptive result reduction.
        
        Args:
            query: Search query string
            goal_context: Current proof goal context for relevance ranking
        
        Returns:
            SearchResult from Coq command execution
        """
        try:
            return self.coq_search.auto_search(query, goal_context)
        except Exception as e:
            self.logger.error(f"Error in Coq command search: {e}")
            error_message = f"Search error: {str(e)}"
            return SearchResult(
                content=error_message,
                source='coq_command',
                relevance_score=0.0,
                metadata={'query': query, 'error': str(e)},
                result_size=len(error_message)
            )
    
    def execute_coq_query(self, query_type: str, identifier: str = None, pattern: str = None, goal_context: str = "") -> SearchResult:
        """Execute a Coq query with adaptive result reduction."""
        return self.coq_search.execute_coq_query(query_type, identifier, pattern, goal_context)
    
