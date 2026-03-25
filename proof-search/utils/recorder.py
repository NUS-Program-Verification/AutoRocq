"""
Proof Statistics Recorder

Records detailed statistics about proof attempts including:
- Proof file name and theorem name
- Number of successful tactics, failed tactics, and query commands
- Number of rollbacks performed during proving
- Raw proving time (total time from start to finish)
- Pure proving time (from first tactic generation to completion)
- Success/failure status
- Additional metadata

Saves results to Excel files for analysis.
"""

import time
import json
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from coqpyt.coq.proof_file import ProofFile
from utils.logger import setup_logger


class ProofRecorder:
    """Records and manages proof attempt statistics."""
    
    def __init__(self, output_dir: str = "data/statistics", auto_save: bool = True):
        """
        Initialize the proof recorder.
        
        Args:
            output_dir: Directory to save statistics files
            auto_save: Whether to auto-save after each proof attempt
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.auto_save = auto_save
        
        # Statistics storage
        self.proof_records: List[Dict[str, Any]] = []
        self.current_session_id = self._generate_session_id()
        
        # Active proof tracking
        self.active_proof: Optional[Dict[str, Any]] = None
        
        self.proving_start_time: Optional[float] = None
        
        self.logger = setup_logger("ProofRecorder")
        
        # Load existing records if available
        self._load_existing_records()
        
        self.logger.info(f"📊 ProofRecorder initialized")
        self.logger.info(f"📁 Output directory: {self.output_dir}")
        self.logger.info(f"📋 Loaded {len(self.proof_records)} existing records")

    def _generate_session_id(self) -> str:
        """Generate a unique session ID for this run."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def _load_existing_records(self):
        """Load existing proof records from JSON file."""
        try:
            json_file = self.output_dir / "proof_statistics.json"
            if json_file.exists():
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    existing_records = data.get('records', [])
                    self.proof_records.extend(existing_records)
            else:
                self.logger.info(f"📄 No existing records file found - starting fresh")
        except Exception as e:
            self.logger.error(f"❌ Failed to load existing records: {e}")
            # Don't clear existing records on error - keep what we have
            pass

    def start_proof_recording(self, proof_file: ProofFile, theorem_name: str = None, metadata: Dict[str, Any] = None):
        """
        Start recording a new proof attempt.
        
        Args:
            proof_file: Path to the proof file
            theorem_name: Name of the theorem being proved
            metadata: Additional metadata to record
        """
        try:
            # End any active recording first
            if self.active_proof:
                self.logger.warning(f"⚠️  Ending previous active proof recording")
                self.end_proof_recording(success=False, message="Interrupted by new proof")
        
            self.proving_start_time = None  # Will be set when first tactic is generated
         
            self.active_proof = {
                'session_id': self.current_session_id,
                'proof_file': proof_file.path,
                'proof_file_full_path': proof_file.path,
                'theorem_name': theorem_name or 'unnamed',
                'start_time': datetime.now().isoformat(),
                'metadata': metadata or {},
                
                # Counters (will be updated during proof)
                'successful_tactics': 0,
                'failed_tactics': 0,
                'query_commands': 0,
                'rollback_history': [],  # List of {at_step, rollback, target_step, reason} dicts
                'total_steps': 0,
                'steps_to_completion': None,
                
                # Time measurement
                'proving_time_seconds': 0.0,
                
                # Result (will be set at end)
                'success': False,
                'completion_message': '',
                'end_time': None,
            }
         
            self.logger.info(f"📊 Started recording proof attempt:")
            self.logger.info(f"   📄 File: {self.active_proof['proof_file']}")
            self.logger.info(f"   🎯 Theorem: {self.active_proof['theorem_name']}")
            self.logger.info(f"   🕒 Start time: {self.active_proof['start_time']}")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to start proof recording: {e}")
            import traceback
            self.logger.error(f"📋 Full error trace: {traceback.format_exc()}")
            self.active_proof = None

    def start_proving_time(self):
        """Record when the first tactic generation starts (proving time begins)."""
        try:
            if not self.active_proof:
                self.logger.warning(f"⚠️  No active proof to record first tactic generation")
                return
            
            if self.proving_start_time is None:
                self.proving_start_time = time.time()
                self.logger.info(f"⏱️  Proving time started (first tactic generation)")
        
        except Exception as e:
            self.logger.error(f"❌ Failed to record first tactic generation: {e}")
    
    def record_rollback(self, at_step: int = None, rollback_steps: int = 1, target_step: int = None, reason: str = ""):
        """
        Record a rollback event during proving.
        
        Args:
            at_step: The step number when rollback was triggered
            rollback_steps: Number of steps rolled back
            target_step: The step number rolled back to
            reason: Reason for the rollback
        """
        try:
            if not self.active_proof:
                self.logger.warning(f"⚠️  No active proof to record rollback")
                return
            
            rollback_event = {
                'at_step': at_step or self.active_proof.get('total_steps', 0),
                'rollback': rollback_steps,
                'target_step': target_step,
                'reason': reason,
            }
            
            self.active_proof['rollback_history'].append(rollback_event)
        
        except Exception as e:
            self.logger.error(f"❌ Failed to record rollback: {e}")
    
    def update_proof_statistics(self, 
                              successful_tactics: int = None,
                              failed_tactics: int = None, 
                              query_commands: int = None,
                              total_steps: int = None,
                              steps_to_completion: int = None):
        """
        Update the current proof statistics.
        
        Args:
            successful_tactics: Number of successful tactics
            failed_tactics: Number of failed tactics
            query_commands: Number of query commands
            total_steps: Total number of steps taken
            steps_to_completion: Number of steps needed to complete the proof (only for successful proofs)
        """
        try:
            if not self.active_proof:
                self.logger.warning(f"⚠️  No active proof to update statistics")
                return
            
            if successful_tactics is not None:
                self.active_proof['successful_tactics'] = successful_tactics
            if failed_tactics is not None:
                self.active_proof['failed_tactics'] = failed_tactics
            if query_commands is not None:
                self.active_proof['query_commands'] = query_commands
            if total_steps is not None:
                self.active_proof['total_steps'] = total_steps
            if steps_to_completion is not None:
                self.active_proof['steps_to_completion'] = steps_to_completion
                        
        except Exception as e:
            self.logger.error(f"❌ Failed to update proof statistics: {e}")
    
    def end_proof_recording(self, success: bool, message: str = "", final_stats: Dict[str, Any] = None):
        """
        End the current proof recording and save the results.
        
        Args:
            success: Whether the proof was successful
            message: Completion message
            final_stats: Final statistics from the proof controller
        """
        try:
            if not self.active_proof:
                self.logger.warning(f"⚠️  No active proof to end recording")
                return None
            
            proving_time = 0.0
            if self.proving_start_time:
                proving_time = time.time() - self.proving_start_time
            
            # Update final statistics
            if final_stats:
                self.active_proof['successful_tactics'] = final_stats.get('successful_tactics', self.active_proof['successful_tactics'])
                self.active_proof['failed_tactics'] = final_stats.get('failed_tactics', self.active_proof['failed_tactics'])
                self.active_proof['query_commands'] = final_stats.get('query_commands', self.active_proof['query_commands'])
                self.active_proof['total_steps'] = final_stats.get('steps_taken', self.active_proof['total_steps'])
                if 'steps_to_completion' in final_stats and final_stats['steps_to_completion'] is not None:
                    self.active_proof['steps_to_completion'] = final_stats['steps_to_completion']
                if 'successful_tactics_list' in final_stats:
                    self.active_proof['successful_tactics_list'] = final_stats['successful_tactics_list']
                if 'query_commands_list' in final_stats:
                    self.active_proof['query_commands_list'] = final_stats['query_commands_list']
            
            # Set completion data
            self.active_proof['success'] = success
            self.active_proof['completion_message'] = message
            self.active_proof['end_time'] = datetime.now().isoformat()
            self.active_proof['proving_time_seconds'] = proving_time
            
            # Calculate derived statistics
            total_tactics = self.active_proof['successful_tactics'] + self.active_proof['failed_tactics']
            success_rate = (self.active_proof['successful_tactics'] / total_tactics * 100) if total_tactics > 0 else 0.0
            self.active_proof['tactic_success_rate'] = success_rate
            
            # Add to records
            completed_record = self.active_proof.copy()
            self.proof_records.append(completed_record)
            
            # Log comprehensive command summary
            self._log_proof_summary(success, proving_time, success_rate, final_stats)
            
            # Auto-save if enabled
            if self.auto_save:
                self.save_records()
            
            # Reset active proof
            result = completed_record.copy()
            self.active_proof = None
            self.proving_start_time = None
        
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Failed to end proof recording: {e}")
            return None
    
    def _log_proof_summary(self, success: bool, proving_time: float, success_rate: float, final_stats: Dict[str, Any] = None):
        """Log a comprehensive summary of all tools used during the proof."""
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"📋 TOOL CALL SUMMARY")
        self.logger.info(f"{'='*60}")
        
        # Result header
        self.logger.info(f"🎯 Result: {'✅ SUCCESS' if success else '❌ FAILED'}")
        self.logger.info(f"📄 Theorem: {self.active_proof.get('theorem_name', 'unnamed')}")
        self.logger.info(f"⏱️  Proving time: {proving_time:.2f}s")
        
        # Successful tactics
        successful_tactics_list = self.active_proof.get('successful_tactics_list', [])
        if final_stats and 'successful_tactics_list' in final_stats:
            successful_tactics_list = final_stats['successful_tactics_list']
        
        if successful_tactics_list:
            self.logger.info(f"✅ Successful tactics used ({len(successful_tactics_list)}):")
            for i, tactic in enumerate(successful_tactics_list, 1):
                self.logger.info(f"   {i}. {tactic}")
        else:
            self.logger.info(f"✅ Successful tactics used: None")
        
        # Failed tactics
        failed_count = self.active_proof.get('failed_tactics', 0)
        self.logger.info(f"❌ Failed tactics attempted: {failed_count}")
        
        # Query commands
        query_commands_list = self.active_proof.get('query_commands_list', [])
        if final_stats and 'query_commands_list' in final_stats:
            query_commands_list = final_stats['query_commands_list']
        
        if query_commands_list:
            self.logger.info(f"🔍 Query commands used ({len(query_commands_list)}):")
            for i, query in enumerate(query_commands_list, 1):
                self.logger.info(f"   {i}. {query}")
        else:
            self.logger.info(f"🔍 Query commands used: None")
        
        # Rollback history
        rollback_history = self.active_proof.get('rollback_history', [])
        
        if rollback_history:
            self.logger.info(f"🔄 Rollbacks performed ({len(rollback_history)}):")
            for i, rb in enumerate(rollback_history, 1):
                self.logger.info(f"   {i}. At step {rb.get('at_step', '?')}: rolled back {rb.get('rollback', '?')} step(s)")
        else:
            self.logger.info(f"🔄 Rollbacks performed: None")
        
        # Summary statistics
        self.logger.info(f"📊 Statistics:")
        self.logger.info(f"   • Successful tactics: {self.active_proof.get('successful_tactics', 0)}")
        self.logger.info(f"   • Failed tactics: {self.active_proof.get('failed_tactics', 0)}")
        self.logger.info(f"   • Query commands: {len(query_commands_list) if query_commands_list else 0}")
        self.logger.info(f"   • Rollbacks: {len(rollback_history)}")
        self.logger.info(f"   • Total steps: {self.active_proof.get('total_steps', 0)}")
        self.logger.info(f"   • Tactic success rate: {success_rate:.1f}%")
        self.logger.info(f"{'='*60}")

    def save_records(self, custom_filename: str = None):
        """
        Save all proof records to JSON and Excel files in append mode.
     
        Args:
            custom_filename: Custom filename prefix (without extension)
        """
        try:
            base_filename = custom_filename or f"proof_statistics"
            
            # ← APPEND MODE: Load existing data first, then append new records
            json_file = self.output_dir / f"{base_filename}.json"
            all_records = []
            
            # Load existing records from file if it exists
            if json_file.exists():
                try:
                    with open(json_file, 'r') as f:
                        existing_data = json.load(f)
                        existing_records = existing_data.get('records', [])
                        
                    # Get existing session IDs to avoid duplicates
                    existing_session_ids = set()
                    for record in existing_records:
                        session_record_id = f"{record.get('session_id', '')}_{record.get('start_time', '')}"
                        existing_session_ids.add(session_record_id)
                    
                    # Add existing records
                    all_records.extend(existing_records)
                    self.logger.info(f"📥 Loaded {len(existing_records)} existing records for append")
                    
                    # Add only new records (avoid duplicates)
                    new_records_count = 0
                    for record in self.proof_records:
                        record_id = f"{record.get('session_id', '')}_{record.get('start_time', '')}"
                        if record_id not in existing_session_ids:
                            all_records.append(record)
                            new_records_count += 1
                    
                    self.logger.info(f"➕ Adding {new_records_count} new records (skipped {len(self.proof_records) - new_records_count} duplicates)")
                    
                except Exception as load_error:
                    self.logger.error(f"❌ Failed to load existing JSON for append: {load_error}")
                    # Fall back to just saving current records
                    all_records = self.proof_records.copy()
            else:
                # No existing file - save all current records
                all_records = self.proof_records.copy()
                self.logger.info(f"📄 No existing JSON file - saving {len(all_records)} records")
     
            # Save combined data to JSON
            data = {
                'last_updated_session_id': self.current_session_id,
                'generated_at': datetime.now().isoformat(),
                'total_records': len(all_records),
                'records': all_records
            }
            
            with open(json_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Save to Excel
            excel_file = self.output_dir / f"{base_filename}.xlsx"
            self._save_to_excel_append_mode(excel_file, all_records)
            self.logger.info(f"💾 Saved {len(all_records)} total records to Excel: {excel_file}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to save records: {e}")
        
    def _save_to_excel_append_mode(self, excel_file: Path, all_records: List[Dict[str, Any]]):
        """Save all records to Excel (existing + new) in append mode."""
        try:
            # Use all_records parameter instead of self.proof_records
            df_data = []
            for record in all_records:
                row = _record_to_base_row(record)
                # Add list fields for Excel
                row['successful_tactics_list'] = "; ".join(record.get('successful_tactics_list', []))
                row['query_commands_list'] = "; ".join(record.get('query_commands_list', []))
                
                # Add metadata columns (if any)
                metadata = record.get('metadata', {})
                for key, value in metadata.items():
                    if key != 'rollback_details':  # Skip rollback details for main table
                        row[f'Meta: {key}'] = value
                
                df_data.append(row)
            
            df = pd.DataFrame(df_data)
            
            if 'session_id' in df.columns and len(df) > 0:
                df = df.sort_values('session_id')
            
            # Save with multiple sheets
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                # Main statistics sheet
                df.to_excel(writer, sheet_name='Proof Statistics', index=False)
                
                # Summary sheet with all data
                summary_data = self._generate_summary_statistics_for_records(all_records)
                summary_df = pd.DataFrame([summary_data])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                # Success/Failure breakdown with all data
                success_breakdown = self._generate_success_breakdown_for_records(all_records)
                success_df = pd.DataFrame(success_breakdown)
                success_df.to_excel(writer, sheet_name='Success Breakdown', index=False)
                
                # Session breakdown to track different runs
                session_breakdown = self._generate_session_breakdown(all_records)
                if session_breakdown:
                    session_df = pd.DataFrame(session_breakdown)
                    session_df.to_excel(writer, sheet_name='Session Breakdown', index=False)
                
                # Rollback analysis sheet
                rollback_analysis = self._generate_rollback_analysis(all_records)
                if rollback_analysis:
                    rollback_df = pd.DataFrame(rollback_analysis)
                    rollback_df.to_excel(writer, sheet_name='Rollback Analysis', index=False)
        
        except Exception as e:
            self.logger.error(f"❌ Failed to save Excel file in append mode: {e}")
            raise

    def _generate_rollback_analysis(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate rollback analysis statistics."""
        analysis = []
        
        for record in records:
            rollback_count = _get_rollback_count(record)
            if rollback_count > 0:  # Only include records with rollbacks
                row = _record_to_base_row(record)
                analysis.append(row)
        
        # Add summary row if there are rollbacks
        if analysis:
            total_rollbacks = sum(r['rollback_count'] for r in analysis)
            rollback_proofs = len(analysis)
            total_proofs = len(records)
            successful_with_rollbacks = len([r for r in analysis[:-1] if r['success'] == 1])
            
            # Calculate average steps to completion for successful proofs with rollbacks
            successful_steps = [r['steps_to_completion'] for r in analysis[:-1] 
                              if r['success'] == 1 and r['steps_to_completion'] != 'N/A' and r['steps_to_completion'] != '']
            avg_completion_steps = round(sum(successful_steps) / len(successful_steps), 1) if successful_steps else 'N/A'
            
            analysis.append({
                'proof_file_full_path': '=== SUMMARY ===',
                'proof_file': '=== SUMMARY ===',
                'theorem_name': f'{rollback_proofs}/{total_proofs} proofs used rollback',
                'success': f'{successful_with_rollbacks}/{rollback_proofs} rollback proofs succeeded',
                'rollback_count': total_rollbacks,
                'successful_tactics': sum(r['successful_tactics'] for r in analysis[:-1]),
                'failed_tactics': sum(r['failed_tactics'] for r in analysis[:-1]),
                'total_steps': sum(r['total_steps'] for r in analysis[:-1]),
                'steps_to_completion': avg_completion_steps,
                'proving_time_seconds': sum(r['proving_time_seconds'] for r in analysis[:-1]),
                'session_id': 'SUMMARY',
            })
        
        return analysis

    def _generate_summary_statistics_for_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate overall summary statistics for given records."""
        if not records:
            return {}
        
        total_proofs = len(records)
        successful_proofs = sum(1 for r in records if r.get('success', False))
        failed_proofs = total_proofs - successful_proofs
        
        # Aggregate statistics
        total_successful_tactics = sum(r.get('successful_tactics', 0) for r in records)
        total_failed_tactics = sum(r.get('failed_tactics', 0) for r in records)
        total_query_commands = sum(r.get('query_commands', 0) for r in records)
        total_rollbacks = sum(_get_rollback_count(r) for r in records)
        total_steps = sum(r.get('total_steps', 0) for r in records)
        
        # Steps to completion statistics (only for successful proofs)
        successful_records = [r for r in records if r.get('success', False)]
        completion_steps = [r.get('steps_to_completion', 0) for r in successful_records 
                           if r.get('steps_to_completion') is not None and r.get('steps_to_completion') != '']
        
        # Rollback statistics
        proofs_with_rollbacks = sum(1 for r in records if _get_rollback_count(r) > 0)
        
        # Time statistics
        proving_times = [r.get('proving_time_seconds', 0.0) for r in records]
        
        summary = {
            'total_proof_attempts': total_proofs,
            'successful_proofs': successful_proofs,
            'failed_proofs': failed_proofs,
            'overall_success_rate': round((successful_proofs / total_proofs * 100), 1) if total_proofs > 0 else 0.0,
            
            'total_successful_tactics': total_successful_tactics,
            'total_failed_tactics': total_failed_tactics,
            'total_query_commands': total_query_commands,
            'total_rollbacks': total_rollbacks,
            'proofs_with_rollbacks': proofs_with_rollbacks,
            'rollback_usage_rate': round((proofs_with_rollbacks / total_proofs * 100), 1) if total_proofs > 0 else 0.0,
            'total_steps': total_steps,
            'overall_tactic_success_rate': round((total_successful_tactics / (total_successful_tactics + total_failed_tactics) * 100), 1) if (total_successful_tactics + total_failed_tactics) > 0 else 0.0,
            
            # Steps to completion statistics
            'avg_steps_to_completion': round(sum(completion_steps) / len(completion_steps), 1) if completion_steps else 'N/A',
            'min_steps_to_completion': min(completion_steps) if completion_steps else 'N/A',
            'max_steps_to_completion': max(completion_steps) if completion_steps else 'N/A',
            'total_completed_proofs': len(completion_steps),
            
            'avg_proving_time_seconds': round(sum(proving_times) / len(proving_times), 2) if proving_times else 0.0,
            'total_proving_time_seconds': round(sum(proving_times), 2),
            'min_proving_time_seconds': round(min(proving_times), 2) if proving_times else 0.0,
            'max_proving_time_seconds': round(max(proving_times), 2) if proving_times else 0.0,
            
            'avg_rollbacks_per_proof': round(total_rollbacks / total_proofs, 2) if total_proofs > 0 else 0.0,
            
            'total_sessions': len(set(r.get('session_id', '') for r in records)),
            'latest_session': max(r.get('session_id', '') for r in records) if records else 'None',
        }
        
        return summary
    

    def _generate_success_breakdown_for_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate success/failure breakdown by file for given records."""
        breakdown = {}
        
        for record in records:
            file_name = record.get('proof_file', 'unknown')
            full_path = record.get('proof_file_full_path', file_name)
            
            # Use full path as the key for more accurate grouping
            grouping_key = full_path if full_path != 'unknown' else file_name
            
            if grouping_key not in breakdown:
                breakdown[grouping_key] = {
                    'proof_file_full_path': full_path,
                    'proof_file': file_name,
                    'total_attempts': 0,
                    'successful_proofs': 0,
                    'failed_proofs': 0,
                    'success_rate': 0.0,
                    'avg_proving_time_seconds': 0.0,
                    'avg_successful_tactics': 0.0,
                    'avg_failed_tactics': 0.0,
                    'avg_query_commands': 0.0,
                    'total_rollbacks': 0,
                    'avg_rollbacks': 0.0,
                    'proofs_with_rollbacks': 0,
                    'avg_steps_to_completion': 'N/A',
                }
            
            breakdown[grouping_key]['total_attempts'] += 1
            if record.get('success', False):
                breakdown[grouping_key]['successful_proofs'] += 1
            else:
                breakdown[grouping_key]['failed_proofs'] += 1
            
            # Track rollback statistics
            rollback_count = _get_rollback_count(record)
            breakdown[grouping_key]['total_rollbacks'] += rollback_count
            if rollback_count > 0:
                breakdown[grouping_key]['proofs_with_rollbacks'] += 1
    
        # Calculate averages
        for grouping_key, data in breakdown.items():
            # Use the grouping key (full path) to filter records more accurately
            file_records = [r for r in records if 
                          (r.get('proof_file_full_path', r.get('proof_file', '')) == grouping_key) or
                          (r.get('proof_file', '') == grouping_key)]
            successful_file_records = [r for r in file_records if r.get('success', False)]
            
            if file_records:
                data['success_rate'] = round((data['successful_proofs'] / data['total_attempts'] * 100), 1)
                data['avg_proving_time_seconds'] = round(sum(r.get('proving_time_seconds', 0.0) for r in file_records) / len(file_records), 2)
                data['avg_successful_tactics'] = round(sum(r.get('successful_tactics', 0) for r in file_records) / len(file_records), 1)
                data['avg_failed_tactics'] = round(sum(r.get('failed_tactics', 0) for r in file_records) / len(file_records), 1)
                data['avg_query_commands'] = round(sum(r.get('query_commands', 0) for r in file_records) / len(file_records), 1)
                data['avg_rollbacks'] = round(data['total_rollbacks'] / data['total_attempts'], 2)
                
                # Average steps to completion for successful proofs
                completion_steps = [r.get('steps_to_completion', 0) for r in successful_file_records 
                                   if r.get('steps_to_completion') is not None and r.get('steps_to_completion') != '']
                data['avg_steps_to_completion'] = round(sum(completion_steps) / len(completion_steps), 1) if completion_steps else 'N/A'
        
        return list(breakdown.values())


    def _generate_session_breakdown(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate breakdown by session ID."""
        session_breakdown = {}
        
        for record in records:
            session_id = record.get('session_id', 'unknown')
            if session_id not in session_breakdown:
                session_breakdown[session_id] = {
                    'session_id': session_id,
                    'total_attempts': 0,
                    'successful_proofs': 0,
                    'failed_proofs': 0,
                    'success_rate': 0.0,
                    'total_proving_time_seconds': 0.0,
                    'avg_proving_time_seconds': 0.0,
                    'total_rollbacks': 0,
                    'avg_rollbacks': 0.0,
                }
            
            session_breakdown[session_id]['total_attempts'] += 1
            if record.get('success', False):
                session_breakdown[session_id]['successful_proofs'] += 1
            else:
                session_breakdown[session_id]['failed_proofs'] += 1
            
            # Track rollbacks
            session_breakdown[session_id]['total_rollbacks'] += _get_rollback_count(record)
    
        # Calculate session statistics
        for session_id, data in session_breakdown.items():
            session_records = [r for r in records if r.get('session_id', '') == session_id]
            
            if session_records:
                data['success_rate'] = round((data['successful_proofs'] / data['total_attempts'] * 100), 1)
                total_time = sum(r.get('proving_time_seconds', 0.0) for r in session_records)
                data['total_proving_time_seconds'] = round(total_time, 2)
                data['avg_proving_time_seconds'] = round(total_time / len(session_records), 2)
                data['avg_rollbacks'] = round(data['total_rollbacks'] / data['total_attempts'], 2)
    
        return list(session_breakdown.values())


    def get_statistics(self) -> Dict[str, Any]:
        """Get current statistics summary."""
        return {
            'total_records': len(self.proof_records),
            'active_proof': self.active_proof is not None,
            'session_id': self.current_session_id,
            'summary': self._generate_summary_statistics_for_records(self.proof_records) if self.proof_records else {}
        }


    def add_metadata_to_active_proof(self, key: str, value: Any):
        """Add metadata to the currently active proof."""
        try:
            if self.active_proof:
                if 'metadata' not in self.active_proof:
                    self.active_proof['metadata'] = {}
                self.active_proof['metadata'][key] = value
                self.logger.debug(f"📝 Added metadata to active proof: {key} = {value}")
            else:
                self.logger.warning(f"⚠️  No active proof to add metadata to")
        except Exception as e:
            self.logger.error(f"❌ Failed to add metadata: {e}")


# Common handling of record


def _get_rollback_count(record: Dict[str, Any]) -> int:
    """Get rollback count from a record, supporting both rollback_history list and rollback_count field."""
    return len(record.get('rollback_history', [])) or record.get('rollback_count', 0)


def _get_steps_to_completion(record: Dict[str, Any]) -> Any:
    """Get steps_to_completion value, returning 'N/A' for failed proofs."""
    if record.get('success', False):
        return record.get('steps_to_completion', '')
    return 'N/A'


def _record_to_base_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a record to a base row dictionary with common fields."""
    return {
        'proof_file_full_path': record.get('proof_file_full_path', record.get('proof_file', '')),
        'proof_file': record.get('proof_file', ''),
        'theorem_name': record.get('theorem_name', ''),
        'success': 1 if record.get('success', False) else 0,
        'successful_tactics': record.get('successful_tactics', 0),
        'failed_tactics': record.get('failed_tactics', 0),
        'query_commands': record.get('query_commands', 0),
        'rollback_count': _get_rollback_count(record),
        'total_steps': record.get('total_steps', 0),
        'steps_to_completion': _get_steps_to_completion(record),
        'tactic_success_rate': round(record.get('tactic_success_rate', 0.0), 1),
        'proving_time_seconds': round(record.get('proving_time_seconds', 0.0), 2),
        'session_id': record.get('session_id', ''),
    }


# Utility functions for easy integration

def create_proof_recorder(output_dir: str = "data/statistics", auto_save: bool = True) -> ProofRecorder:
    """Create a new ProofRecorder instance."""
    return ProofRecorder(output_dir=output_dir, auto_save=auto_save)

def format_time_duration(seconds: float) -> str:
    """Format time duration in a human-readable format."""
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"
    else:
        hours = int(seconds // 3600)
        remaining_minutes = int((seconds % 3600) // 60)
        remaining_seconds = seconds % 60
        return f"{hours}h {remaining_minutes}m {remaining_seconds:.0f}s"

def export_records_to_csv(recorder: ProofRecorder, output_file: str):
    """Export proof records to CSV format."""
    try:
        df_data = []
        for record in recorder.proof_records:
            row = _record_to_base_row(record)
            # Add list fields for CSV
            row['successful_tactics_list'] = "; ".join(record.get('successful_tactics_list', []))
            row['query_commands_list'] = "; ".join(record.get('query_commands_list', []))
            df_data.append(row)

        df = pd.DataFrame(df_data)
        df.to_csv(output_file, index=False)

    except Exception as e:
        print(f"Failed to export to CSV: {e}")
