import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from utils.logger import setup_logger
from utils.coq_utils import extract_goal_pattern, count_goals, calculate_similarity, calculate_text_similarity

@dataclass
class TacticHistoryEntry:
    """A single tactic history entry."""
    tactic: str
    goals_before: str
    goals_after: str
    hypotheses_before: str
    hypotheses_after: str
    theorem_name: str
    timestamp: datetime
    step_number: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'tactic': self.tactic,
            'goals_before': self.goals_before,
            'goals_after': self.goals_after,
            'hypotheses_before': self.hypotheses_before,
            'hypotheses_after': self.hypotheses_after,
            'theorem_name': self.theorem_name,
            'timestamp': self.timestamp.isoformat(),
            'step_number': self.step_number
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TacticHistoryEntry':
        """Create TacticHistoryEntry from dictionary."""
        try:
            # Parse timestamp
            if isinstance(data['timestamp'], str):
                timestamp = datetime.fromisoformat(data['timestamp'])
            else:
                timestamp = data['timestamp']
            
            return cls(
                tactic=data['tactic'],
                goals_before=data['goals_before'],
                goals_after=data['goals_after'],
                hypotheses_before=data.get('hypotheses_before', ''),
                hypotheses_after=data.get('hypotheses_after', ''),
                theorem_name=data['theorem_name'],
                timestamp=timestamp,
                step_number=data.get('step_number')
            )
        except Exception as e:
            setup_logger("TacticHistoryManager").error(f"Error creating TacticHistoryEntry from dict: {e}")
            # Return a minimal entry to avoid crashes
            return cls(
                tactic="unknown",
                goals_before="",
                goals_after="",
                hypotheses_before="",
                hypotheses_after="",
                theorem_name="unknown",
                timestamp=datetime.now(),
                step_number=None
            )


class TacticHistoryManager:
    """Manages successful tactic history for learning."""
    
    def __init__(self, history_file: str = "tactic_history.json"):
        # Always convert to absolute path to avoid path mismatch issues
        if not os.path.isabs(history_file):
            # Get the project root directory (proof-search)
            current_file = Path(__file__)  # This file is in agent/ directory
            project_root = current_file.parent.parent  # Go up to proof-search directory
            data_dir = project_root / "data"
            
            # Ensure data directory exists
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # Create absolute path
            self.history_file = data_dir / history_file
        else:
            self.history_file = Path(history_file)
        
        self.entries: List[TacticHistoryEntry] = []
        self.logger = setup_logger("TacticHistoryManager")
        
        # Log the resolved path for debugging
        self.logger.info(f"📁 TacticHistoryManager initialized with path: {self.history_file}")
        
        # Maintain sets of stored signatures for fast duplicate checking
        self._tactic_signatures: set = set()
        
        # Load existing history
        self.load_history()
    
    def _create_tactic_signature(
        self, 
        tactic: str, 
        goals_before: str, 
        goals_after: str, 
        theorem_name: str
    ) -> str:
        """Create a unique signature for a tactic entry to detect duplicates.
        
        Only treat as duplicate when tactic, goals_before, AND goals_after are all identical.
        Same tactics with different proof states should be saved separately.
        """
        try:
            # Normalize inputs by stripping whitespace and converting to lowercase
            tactic_clean = tactic.strip().lower()
            goals_before_clean = goals_before.strip().lower()
            goals_after_clean = goals_after.strip().lower()
            
            # Create signature based on ALL THREE key fields (excluding theorem_name)
            # We don't include theorem_name because the same tactic+states might appear
            # in different theorems and should still be considered duplicates
            signature = f"{tactic_clean}|||{goals_before_clean}|||{goals_after_clean}"
            
            return signature
            
        except Exception as e:
            self.logger.error(f"Error creating tactic signature: {e}")
            # Return a fallback signature to prevent blocking
            return f"{tactic}|||{hash(goals_before)}|||{hash(goals_after)}"

    def add_successful_tactic(
        self, 
        tactic: str, 
        goals_before: str, 
        goals_after: str, 
        theorem_name: str, 
        hypotheses_before: str = "",
        hypotheses_after: str = "",
        step_number: int = None
    ):
        """Add a successful tactic to history, avoiding duplicates.
        
        Only skips entries when tactic, goals_before, AND goals_after are all identical.
        Same tactics with different proof states are saved as separate entries.
        """
        try:
            # Create tactic signature for duplicate checking
            signature = self._create_tactic_signature(tactic, goals_before, goals_after, theorem_name)
            
            # Check for duplicate using the signature set (O(1) lookup)
            if signature in self._tactic_signatures:
                self.logger.debug(f"🔄 Skipping exact duplicate: {tactic.strip()}")
                self.logger.debug(f"   - Same tactic with identical before/after states already exists")
                return
            
            entry = TacticHistoryEntry(
                tactic=tactic,
                goals_before=goals_before,
                goals_after=goals_after,
                hypotheses_before=hypotheses_before,
                hypotheses_after=hypotheses_after,
                theorem_name=theorem_name,
                timestamp=datetime.now(),
                step_number=step_number
            )
            
            # Add to entries and signature set
            self.entries.append(entry)
            self._tactic_signatures.add(signature)
            
            self.logger.debug(f"✅ Added tactic: {tactic.strip()}")
            self.logger.debug(f"   - New entry #{len(self.entries)}, unique signature created")
            
        except Exception as e:
            self.logger.error(f"Error adding successful tactic: {e}")

    def save_history(self):
        """Save history to file with enhanced error handling."""
        try:
            # Ensure the directory exists
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert entries to dictionaries
            data = {
                'entries': [entry.to_dict() for entry in self.entries],
                'metadata': {
                    'total_entries': len(self.entries),
                    'unique_signatures': len(self._tactic_signatures) if hasattr(self, '_tactic_signatures') else 0,
                    'last_updated': datetime.now().isoformat(),
                    'version': '2.0'
                }
            }
            
            # Write to file with atomic operation
            temp_file = self.history_file.with_suffix('.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Atomic replace
            temp_file.replace(self.history_file)
            
            self.logger.info(f"💾 Saved {len(self.entries)} entries to {self.history_file}")
            
        except Exception as e:
            self.logger.error(f"❌ Error saving history: {e}")
            # Try to save to backup location
            try:
                backup_file = self.history_file.with_suffix('.backup.json')
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump({'entries': [entry.to_dict() for entry in self.entries]}, f, indent=2)
                self.logger.warning(f"⚠️ Saved backup to {backup_file}")
            except Exception as backup_error:
                self.logger.error(f"❌ Backup save also failed: {backup_error}")

    def load_history(self):
        """Load history from file and rebuild signature set with enhanced error handling."""
        try:
            if self.history_file.exists():
                self.logger.info(f"📂 Loading history from {self.history_file}")
                
                # Check if file is empty or very small
                file_size = self.history_file.stat().st_size
                if file_size == 0:
                    self.logger.warning(f"⚠️ History file is empty: {self.history_file}")
                    self.entries = []
                    self._tactic_signatures = set()
                    return
                
                if file_size < 10:  # Very small file, likely corrupted
                    self.logger.warning(f"⚠️ History file too small ({file_size} bytes): {self.history_file}")
                    # Try to read and show content for debugging
                    try:
                        with open(self.history_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        self.logger.warning(f"⚠️ File content: '{content}'")
                    except Exception:
                        pass
                    
                    # Initialize empty and return
                    self.entries = []
                    self._tactic_signatures = set()
                    return
                
                # Try to read and parse JSON
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    
                if not content:
                    self.logger.warning(f"⚠️ History file contains only whitespace: {self.history_file}")
                    self.entries = []
                    self._tactic_signatures = set()
                    return
                
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as json_error:
                    self.logger.error(f"❌ JSON decode error: {json_error}")
                    self.logger.error(f"🔍 File content preview: '{content[:200]}...'")
                    
                    # Try to recover by moving corrupted file and starting fresh
                    backup_path = self.history_file.with_suffix('.corrupted.backup')
                    try:
                        self.history_file.rename(backup_path)
                        self.logger.warning(f"⚠️ Moved corrupted file to: {backup_path}")
                    except Exception as move_error:
                        self.logger.error(f"❌ Failed to backup corrupted file: {move_error}")
                    
                    # Initialize empty
                    self.entries = []
                    self._tactic_signatures = set()
                    return
                
                # Process the loaded data
                entries_data = data.get('entries', [])
                if isinstance(data, list):  # Handle old format
                    entries_data = data
                
                self.entries = []
                loaded_count = 0
                skipped_count = 0
                
                for i, entry_data in enumerate(entries_data):
                    try:
                        entry = TacticHistoryEntry.from_dict(entry_data)
                        self.entries.append(entry)
                        loaded_count += 1
                    except Exception as entry_error:
                        self.logger.warning(f"⚠️ Skipping corrupted entry {i}: {entry_error}")
                        skipped_count += 1
                
                # Rebuild signature sets from loaded entries
                self._rebuild_signature_set()
                
                self.logger.info(f"✅ Loaded {loaded_count} tactic entries from {self.history_file}")
                if skipped_count > 0:
                    self.logger.warning(f"⚠️ Skipped {skipped_count} corrupted entries")
                
                # Log metadata if available
                metadata = data.get('metadata', {}) if isinstance(data, dict) else {}
                if metadata:
                    self.logger.info(f"📊 Metadata: {metadata}")
                
            else:
                self.logger.info(f"📂 No existing history file found at {self.history_file}")
                self.entries = []
                self._tactic_signatures = set()
                self.logger.info(f"✅ Initialized empty history manager")
                
        except Exception as e:
            self.logger.error(f"❌ Failed to load history: {e}")
            
            # Enhanced error recovery
            try:
                # Check if file exists and get basic info
                if self.history_file.exists():
                    file_size = self.history_file.stat().st_size
                    self.logger.error(f"🔍 File exists, size: {file_size} bytes")
                    
                    # Try to read first few characters for debugging
                    try:
                        with open(self.history_file, 'r', encoding='utf-8') as f:
                            preview = f.read(100)
                        self.logger.error(f"🔍 File preview: '{preview}'")
                    except Exception as read_error:
                        self.logger.error(f"🔍 Cannot read file: {read_error}")
                    
                    # Create backup of problematic file
                    try:
                        import time
                        timestamp = int(time.time())
                        backup_path = self.history_file.with_suffix(f'.error_backup_{timestamp}.json')
                        self.history_file.rename(backup_path)
                        self.logger.warning(f"⚠️ Moved problematic file to: {backup_path}")
                    except Exception as backup_error:
                        self.logger.error(f"❌ Failed to backup problematic file: {backup_error}")
                        
                else:
                    self.logger.error(f"🔍 File does not exist: {self.history_file}")
                    
            except Exception as debug_error:
                self.logger.error(f"❌ Error during debug analysis: {debug_error}")
            
            # Always initialize empty state on any error
            self.entries = []
            self._tactic_signatures = set()
            self.logger.info(f"🔄 Initialized empty history after error recovery")

    def _rebuild_signature_set(self):
        """Rebuild signature sets from existing entries."""
        try:
            self._tactic_signatures = set()
            for entry in self.entries:
                signature = self._create_tactic_signature(
                    entry.tactic,
                    entry.goals_before, 
                    entry.goals_after,
                    entry.theorem_name
                )
                self._tactic_signatures.add(signature)

            
            self.logger.debug(f"🔄 Rebuilt signature sets: {len(self._tactic_signatures)} tactics")
            
        except Exception as e:
            self.logger.error(f"Error rebuilding signature set: {e}")
            self._tactic_signatures = set()

    def clear_history(self):
        """Clear all history entries and signature sets."""
        try:
            self.entries = []
            self._tactic_signatures = set()
            self.logger.info("Cleared all history entries")
            
        except Exception as e:
            self.logger.error(f"Error clearing history: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the tactic history."""
        if not self.entries:
            return {"total_entries": 0}
        
        tactic_counts = {}
        pattern_counts = {}
        
        for entry in self.entries:
            # Count tactics
            tactic = entry.tactic.split()[0] if entry.tactic else 'unknown'  # First word of tactic
            tactic_counts[tactic] = tactic_counts.get(tactic, 0) + 1
            
            # Count patterns
            pattern = extract_goal_pattern(entry.goals_before)
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        
        # Calculate goals solved (difference between before and after goal counts)
        total_goals_solved = 0
        for entry in self.entries:
            goals_before_count = count_goals(entry.goals_before)
            goals_after_count = count_goals(entry.goals_after)
            goals_solved = max(0, goals_before_count - goals_after_count)
            total_goals_solved += goals_solved
        
        avg_goals_solved = total_goals_solved / len(self.entries) if self.entries else 0
        
        return {
            "total_entries": len(self.entries),
            "unique_signatures": len(self._tactic_signatures),
            "unique_tactics": len(tactic_counts),
            "most_common_tactics": sorted(tactic_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "goal_patterns": pattern_counts,
            "average_goals_solved": avg_goals_solved,
            "theorems_covered": len(set(entry.theorem_name for entry in self.entries if entry.theorem_name)),
            "total_goals_solved": total_goals_solved
        }

    def get_similar_history(self, current_proof_state: str, n: int = 5) -> List[Dict[str, str]]:
        """Get top-n most similar history entries based on current proof state.
        
        Args:
            current_proof_state: Current goals/proof state as string
            n: Number of top similar entries to return
            
        Returns:
            List of dictionaries containing tactic, goals_before, goals_after
        """
        try:
            if not self.entries or not current_proof_state:
                self.logger.debug(f"🔍 No entries ({len(self.entries)}) or empty proof state")
                return []
            
            # Extract pattern from current proof state
            current_pattern = extract_goal_pattern(current_proof_state)
            self.logger.debug(f"🔍 Current pattern: {current_pattern[:100]}...")
            
            # Calculate similarities for all entries
            similarities = []
            for i, entry in enumerate(self.entries):
                try:
                    # Calculate similarity based on goals_before pattern
                    entry_pattern = extract_goal_pattern(entry.goals_before)
                    similarity_score = calculate_similarity(current_pattern, entry_pattern)
                    
                    # Also consider textual similarity for more nuanced matching
                    text_similarity = calculate_text_similarity(current_proof_state, entry.goals_before)
                    
                    # Combine pattern and text similarity (weighted average)
                    combined_score = 0.7 * similarity_score + 0.3 * text_similarity
                    
                    similarities.append({
                        'index': i,
                        'entry': entry,
                        'similarity': combined_score,
                        'pattern_sim': similarity_score,
                        'text_sim': text_similarity
                    })
                    
                except Exception as entry_error:
                    self.logger.warning(f"⚠️ Error processing entry {i}: {entry_error}")
                    continue
            
            # Sort by similarity score (descending)
            similarities.sort(key=lambda x: x['similarity'], reverse=True)
            
            # Take top-n entries
            top_similar = similarities[:n]
            
            # Convert to required JSON format
            result = []
            for item in top_similar:
                entry = item['entry']
                similarity = item['similarity']
                
                result.append({
                    "tactic": entry.tactic,
                    "goals_before": entry.goals_before,
                    "goals_after": entry.goals_after,
                    "similarity_score": round(similarity, 3)  # For debugging, can be removed
                })
            
            self.logger.debug(f"🔍 Found {len(result)} similar entries out of {len(self.entries)} total")
            if result:
                self.logger.debug(f"   - Top similarity: {result[0].get('similarity_score', 0):.3f}")
                self.logger.debug(f"   - Top tactic: {result[0]['tactic'][:50]}...")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error finding similar history: {e}")
            return []
        
    def get_recent_tactics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent successful tactics from history.
        
        Args:
            limit: Maximum number of recent entries to return
            
        Returns:
            List of dictionaries containing tactic history data
        """
        try:
            if not self.entries:
                self.logger.debug(f"🔍 No history entries available")
                return []
            
            # Get the most recent entries (last 'limit' entries)
            recent_entries = self.entries[-limit:] if len(self.entries) > limit else self.entries
            
            # Convert TacticHistoryEntry objects to dictionaries
            result = []
            for entry in recent_entries:
                try:
                    entry_dict = {
                        'tactic': entry.tactic,
                        'goals_before': entry.goals_before,
                        'goals_after': entry.goals_after,
                        'hypotheses_before': entry.hypotheses_before,
                        'hypotheses_after': entry.hypotheses_after,
                        'theorem_name': entry.theorem_name,
                        'timestamp': entry.timestamp.isoformat() if hasattr(entry.timestamp, 'isoformat') else str(entry.timestamp),
                        'step_number': entry.step_number
                    }
                    result.append(entry_dict)
                    
                except Exception as entry_error:
                    self.logger.warning(f"⚠️ Error converting entry to dict: {entry_error}")
                    continue
            
            self.logger.debug(f"🔍 Retrieved {len(result)} recent tactics from history (limit: {limit})")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error getting recent tactics: {e}")
            return []
    
    def get_tactics_for_theorem(self, theorem_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get tactics specific to a theorem.
        
        Args:
            theorem_name: Name of the theorem to filter by
            limit: Maximum number of entries to return
            
        Returns:
            List of dictionaries containing tactic history data for the theorem
        """
        try:
            if not self.entries or not theorem_name:
                return []
            
            # Filter entries by theorem name
            theorem_entries = [
                entry for entry in self.entries 
                if entry.theorem_name == theorem_name
            ]
            
            # Get the most recent entries for this theorem
            recent_entries = theorem_entries[-limit:] if len(theorem_entries) > limit else theorem_entries
            
            # Convert to dictionaries
            result = []
            for entry in recent_entries:
                try:
                    entry_dict = {
                        'tactic': entry.tactic,
                        'goals_before': entry.goals_before,
                        'goals_after': entry.goals_after,
                        'hypotheses_before': entry.hypotheses_before,
                        'hypotheses_after': entry.hypotheses_after,
                        'theorem_name': entry.theorem_name,
                        'timestamp': entry.timestamp.isoformat() if hasattr(entry.timestamp, 'isoformat') else str(entry.timestamp),
                        'step_number': entry.step_number
                    }
                    result.append(entry_dict)
                    
                except Exception as entry_error:
                    self.logger.warning(f"⚠️ Error converting theorem entry to dict: {entry_error}")
                    continue
            
            self.logger.debug(f"🔍 Retrieved {len(result)} tactics for theorem '{theorem_name}' (limit: {limit})")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error getting tactics for theorem: {e}")
            return []