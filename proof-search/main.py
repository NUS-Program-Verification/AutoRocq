#!/usr/bin/env python3
"""
Main entry point for the proof agent.
Orchestrates the proof search process using LLM-generated tactics.
"""

import sys
import argparse
import logging
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import contextmanager

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_controller import ProofController

from utils.config import load_config, ProofAgentConfig
from utils.logger import setup_logger, global_logger


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated Coq proof agent using LLM-generated tactics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                        # Uses default config with default proof file
  python main.py examples/example.v     # Uses specific proof file with default config
  python main.py examples/example.v --theorem mult_0_plus
  python main.py examples/example.v --config config.json --max-steps 100
        """
    )
    
    parser.add_argument(
        "proof_file",
        nargs='?',
        help="Path to the Coq proof file (.v). If not specified, uses proof_file_path from config."
    )
    
    parser.add_argument(
        "--theorem", "-t",
        help="Specific theorem name to prove (if not specified, proves current theorem in file)"
    )
    
    parser.add_argument(
        "--config", "-c",
        help="Path to configuration file (JSON format)"
    )
    
    parser.add_argument(
        "--plan", "-p", 
        help="Path to proof plan file (default: none)"
    )
    
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum number of proof steps to attempt (default: from config or 50)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging level (default: from config or INFO)"
    )
    
    parser.add_argument(
        "--library-path", 
        action="append", 
        nargs=2,
        metavar=("PATH", "NAME"),
        help="Add custom library path mapping: --library-path /path/to/lib libname"
    )
    
    parser.add_argument(
        "--coqproject-option", 
        action="append",
        help="Add extra option to _CoqProject file"
    )
    
    parser.add_argument(
        "--workspace", 
        help="Set workspace directory"
    )

    parser.add_argument(
        "--local-session-caching",
        action="store_true",
        help="Use local session caching (stored to a local file)"
    )
    
    return parser.parse_args()


def validate_arguments(args, config: ProofAgentConfig) -> bool:
    """Validate command line arguments with config fallback."""
    # Determine which proof file to use
    proof_file = args.proof_file
    if not proof_file:
        # Use proof file from config
        if hasattr(config.coq, 'proof_file_path') and config.coq.proof_file_path:
            proof_file = config.coq.proof_file_path
            print(f"Using proof file from config: {proof_file}")
        else:
            print("Error: No proof file specified and none found in config")
            return False
    
    # Update args with the determined proof file
    args.proof_file = proof_file
    
    # Check if proof file exists
    if not Path(proof_file).exists():
        print(f"Error: Proof file '{proof_file}' not found")
        return False
    
    # Check if proof file has .v extension
    if not proof_file.endswith('.v'):
        print(f"Warning: Proof file '{proof_file}' does not have .v extension")
    
    # Check if config file exists (if specified)
    if args.config and not Path(args.config).exists():
        print(f"Error: Config file '{args.config}' not found")
        return False

    # Validate plan file
    if args.plan and not Path(args.plan).exists():
        print(f"Error: Plan file '{args.plan}' not found")
        return False
    
    # Validate max_steps
    if args.max_steps is not None and args.max_steps <= 0:
        print(f"Error: max-steps must be positive, got {args.max_steps}")
        return False
    
    return True


def setup_output_directory(output_dir: Optional[str]) -> Path:
    """Setup output directory for logs, visualizations, etc."""
    if output_dir:
        output_path = Path(output_dir)
    else:
        # Default: create output directory next to proof file
        proof_file_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
        output_path = proof_file_path.parent / f"autorocq-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    output_path.mkdir(exist_ok=True)
    return output_path


def initialize_components(args, config: ProofAgentConfig, logger) -> Dict[str, Any]:
    """Initialize all proof agent components."""
    logger.info("Initializing proof agent components...")
    
    try:
        # Process library paths from command line
        library_paths = getattr(config.coq, 'library_paths', [])
        if args.library_path:
            for path, name in args.library_path:
                library_paths.append({"path": path, "name": name})
                logger.info(f"   Added library path from CLI: {path} -> {name}")
        
        # Process extra CoqProject options from command line
        coqproject_extra_options = getattr(config.coq, 'coqproject_extra_options', [])
        if args.coqproject_option:
            coqproject_extra_options.extend(args.coqproject_option)
            logger.info(f"   Added CoqProject options from CLI: {args.coqproject_option}")
        
        # Set workspace - use file directory if not specified
        workspace = args.workspace or getattr(config.coq, 'workspace', None)
        if not workspace:
            workspace = str(Path(args.proof_file).parent)
            logger.info(f"   Using file directory as workspace: {workspace}")
        
        # Initialize Coq interface with library support
        if len(library_paths) > 0:
            logger.info(f"📚 Configuring libraries:")
            for lib in library_paths:
                logger.info(f"   - {lib['name']}: {lib['path']}")
            logger.info(f"🔧 Auto setup CoqProject: {getattr(config.coq, 'auto_setup_coqproject', True)}")
        
        # If hammer is enabled, add hammer library import to proof file
        if config.enable_hammer:
            logger.info("🔧 Hammer enabled. Importing hammer library...")
            with open(args.proof_file, 'r', encoding='utf-8') as f:
                content = f.read()
            if "From Hammer Require Import Hammer." not in content:
                with open(args.proof_file, 'w', encoding='utf-8') as f:
                    f.write("From Hammer Require Import Hammer.\nFrom Hammer Require Import Tactics.\n\n" + content)
            else:
                logger.debug("🔧 Hammer already imported - skipping")
        
        coq_interface = CoqInterface(
            file_path=args.proof_file,
            workspace=workspace,
            library_paths=library_paths,
            auto_setup_coqproject=getattr(config.coq, 'auto_setup_coqproject', True),
            coqproject_extra_options=coqproject_extra_options,
            timeout=getattr(config.coq, 'timeout', 60)
        )
        
        # Load the file using proper method
        success = coq_interface.load()
        if not success:
            error_msg = coq_interface.get_last_error()
            logger.error(f"❌ {error_msg}")
            raise Exception(f"Failed to load Coq file")
        
        logger.info("✅ File loaded successfully")
        
        # Get proof status to verify loading
        status = coq_interface.get_proof_status()
        logger.info(f"📊 Proof status: loaded={status.get('has_proof')}, steps={status.get('proof_steps')}")
        
        if not status.get("has_proof", False):
            logger.warning("⚠️ No proof found in file - this may be expected for some files")
        else:
            logger.info(f"✅ Found proof with {status['proof_steps']} initial steps")

        # Setup history file path
        history_file = Path("data") / "tactic_history.json"
        history_file.parent.mkdir(exist_ok=True)
        
        # Setup plan file path
        plan_file = Path(args.plan) if args.plan else None
        proof_plan = None
        if plan_file and plan_file.exists():
            logger.info(f"📄 Using proof plan from: {plan_file}")
            with open(plan_file, 'r', encoding='utf-8') as f:
                proof_plan = f.read()
        
        # Initialize tactic generator with history
        logger.info("Initializing tactic generator...")
        context_manager = ContextManager(
            coq_interface=coq_interface,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=getattr(config.llm, 'api_key', None),
            api_base=getattr(config.llm, 'api_base', None),
            max_tokens=getattr(config.llm, 'max_tokens', 2000),
            timeout=getattr(config.llm, 'timeout', 30),
            history_file=str(history_file),
            enable_history_context=config.enable_history_context,
            enable_context_search=config.enable_context_search,
            enable_rollback=config.enable_rollback,
            enable_caching=getattr(config.llm, 'enable_caching', True),
            proof_plan=proof_plan,
            enable_local_session_caching=args.local_session_caching
        )
        
        # Initialize controller with history
        logger.info("Initializing proof controller...")
        controller = ProofController(
            coq_interface=coq_interface,
            context_manager=context_manager,
            max_steps=config.coq.max_steps,
            max_errors=config.max_errors,
            enable_recording=config.enable_recording,
            enable_error_feedback=config.enable_error_feedback,
            enable_hammer=config.enable_hammer,
            max_context_search=config.max_context_search,
            history_file=str(history_file)
        )
        
        return {
            "coq_interface": coq_interface,
            "context_manager": context_manager,
            "coq_chat_session": context_manager.chat_session,
            "controller": controller
        }
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        import traceback
        traceback.print_exc()
        raise


def print_initial_state(components: Dict[str, Any], logger):
    """Print initial proof state information."""
    coq = components["coq_interface"]
    
    logger.info("=== Initial Proof State ===")
    
    # Get proof status first
    status = coq.get_proof_status()
    logger.info(f"📊 Proof status: loaded={status.get('has_proof')}, steps={status.get('proof_steps')}")
    
    if not status.get("has_proof", False):
        logger.info("No proof available in file")
        return
    
    # Check if we have an active proof
    unproven_proof = coq.get_unproven_proof()
    if not unproven_proof:
        logger.info("No unproven proof available")
        return
    
    logger.info(f"Unproven proof found with {len(unproven_proof.steps)} steps")
    
    # Print hypotheses
    try:
        hypotheses = coq.get_hypothesis()
        if hypotheses:
            logger.info(f"Hypotheses: {hypotheses}")
        else:
            logger.info("No hypotheses")
    except Exception as e:
        logger.warning(f"Could not retrieve hypotheses: {e}")
    
    # Print proof steps so far
    logger.info("Current proof steps:")
    try:
        if coq.proof and coq.proof.steps:
            for i, step in enumerate(coq.proof.steps):
                logger.info(f"  {i+1}: {step.text.strip()}")
        else:
            logger.info("  No steps available")
    except Exception as e:
        logger.warning(f"Could not print proof steps: {e}")
    
    # Print context information
    logger.info("Available context terms:")
    try:
        terms = coq.get_context_terms()
        logger.info(f"Found {len(terms)} context terms")
    except Exception as e:
        logger.warning(f"Could not retrieve context terms: {e}")

@contextmanager  
def timeout_context(seconds):
    """Context manager for timeout operations."""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {seconds} seconds")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def cleanup_components(components: Dict[str, Any], logger):
    """Clean up resources with timeout protection and forceful termination."""
    try:
        logger.info("Cleaning up resources...")
        
        # Save tactic history first (most important) with timeout
        controller = components.get("controller")
        if controller and hasattr(controller, 'tactic_history'):
            try:
                logger.info("Saving tactic history...")
                with timeout_context(3):  # 3 second timeout
                    controller.tactic_history.save_history()
                    logger.info("Tactic history saved successfully")
            except TimeoutError:
                logger.warning("Tactic history save timed out")
            except Exception as e:
                logger.warning(f"Failed to save tactic history: {e}")
        
        # Close Coq interface with timeout
        coq = components.get("coq_interface")
        if coq and hasattr(coq, 'close'):
            try:
                logger.info("Closing Coq interface...")
                with timeout_context(2):  # 2 second timeout
                    coq.close()
                    logger.info("Coq interface closed successfully")
            except TimeoutError:
                coq.force_close()
                logger.warning("Coq interface close timed out; force closing")
            except Exception as e:
                logger.warning(f"Error closing Coq interface: {e}")
        
        # Reset other components quickly
        for name, component in components.items():
            if name in ['coq_interface', 'controller']:
                continue
            if hasattr(component, 'reset'):
                try:
                    with timeout_context(1):
                        component.reset()
                        logger.debug(f"Reset component: {name}")
                except:
                    logger.warning(f"Failed to reset {name}")
                
    except Exception as e:
        logger.error(f"Critical error during cleanup: {e}")
    finally:
        logger.info("Cleanup completed")

def clean_proof_file(file_path: str, logger) -> bool:
    """
    Clean proof file by removing tactics between Proof. and Qed./Admitted.
    Changes Qed to Admitted to make proof unproven.
    If multiple theorems exist, cleans the last one.
    """
    try:
        logger.info("🧹 Attempting Python-based proof file cleaning...")
        
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        logger.info(f"📄 Read file: {len(content)} characters")
        
        # Count theorems
        import re
        theorem_pattern = r'\b(Theorem|Lemma|Corollary|Proposition)\b'
        theorems = list(re.finditer(theorem_pattern, content, re.IGNORECASE))
        
        if len(theorems) == 0:
            logger.warning("⚠️ No theorems found in file")
            return False
        
        logger.info(f"✅ Found {len(theorems)} lemmas/theorems")
        
        # Find all Proof. statements
        proof_matches = list(re.finditer(r'Proof\s*\.', content, re.IGNORECASE))
        
        if not proof_matches:
            logger.warning("⚠️ Could not find any 'Proof.' in file")
            return False
        
        # Use the last Proof. (corresponding to the last theorem)
        last_proof_match = proof_matches[-1]
        proof_start_pos = last_proof_match.end()
        logger.info(f"📋 Found last 'Proof.' at position {last_proof_match.start()}")
        
        # Find the ending (Qed. or Admitted.) after the last Proof.
        ending_pattern = r'(Qed|Admitted)\s*\.'
        ending_match = re.search(ending_pattern, content[proof_start_pos:], re.IGNORECASE)
        
        if ending_match:
            # Found complete proof
            ending_pos = proof_start_pos + ending_match.start()
            tactics_content = content[proof_start_pos:ending_pos]
            ending_text = ending_match.group(0)
            
            logger.info(f"📋 Found proof ending: '{ending_text}' at position {ending_pos}")
            logger.info(f"   Tactics content: {len(tactics_content.strip())} characters")
            
            if tactics_content.strip():
                logger.info(f"   Preview: {tactics_content.strip()[:150]}{'...' if len(tactics_content.strip()) > 150 else ''}")
            
            # Replace everything between Proof. and ending with just newline + Admitted.
            new_content = content[:proof_start_pos] + "\nAdmitted."
            
            # Check if there's content after the ending - preserve it
            content_after_ending = content[proof_start_pos + ending_match.end():]
            if content_after_ending.strip():
                logger.info(f"   Preserving {len(content_after_ending.strip())} characters after ending")
                new_content += content_after_ending
            
            ending_change = f"{ending_text} -> Admitted."
            
        else:
            # No ending found - incomplete proof
            logger.info("📋 No proof ending found (incomplete proof)")
            tactics_content = content[proof_start_pos:]
            
            logger.info(f"   Tactics content: {len(tactics_content.strip())} characters")
            if tactics_content.strip():
                logger.info(f"   Preview: {tactics_content.strip()[:150]}{'...' if len(tactics_content.strip()) > 150 else ''}")
            
            # Replace from Proof. to end with Admitted.
            new_content = content[:proof_start_pos] + "\nAdmitted."
            ending_change = "(incomplete) -> Admitted."
        
        # Create backup first
        backup_path = file_path + '.backup'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"💾 Created backup: {backup_path}")
        
        # Write the cleaned content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        logger.info("✅ Successfully cleaned proof file")
        if tactics_content.strip():
            logger.info(f"   Removed: {len(tactics_content.strip())} characters of tactics")
        logger.info(f"   Changed: {ending_change}")
        logger.info(f"   Result: Proof. -> Admitted.")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to clean proof file: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point with history management."""
    
    global components, logger, exit_code
    components = {}
    logger = None
    exit_code = 1
    
    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        print(f"\n⚠️ Received {sig_name} signal - initiating cleanup...")
        
        if components and logger:
            cleanup_components(components, logger)
        
        sys.exit(128 + signum)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill command
    
    # Parse arguments
    args = parse_arguments()
    
    # Load configuration FIRST (before validation)
    print(f"🔧 Loading configuration...")
    if args.config:
        print(f"   Using config file: {args.config}")
        config = load_config(args.config)
    else:
        print(f"   Using default configuration")
        config = load_config()
    
    # NOW validate arguments with config context
    if not validate_arguments(args, config):
        sys.exit(1)
    
    # Setup output directory
    output_dir = setup_output_directory(config.output_dir)
    
    # Use absolute path
    args.proof_file = str(Path(args.proof_file).resolve())
    
    # Update proof file path in config for logging/tracking
    config.coq.proof_file_path = args.proof_file
    
    # Override config with command line arguments ONLY if they were explicitly provided
    config.coq.max_steps = args.max_steps or config.coq.max_steps
    config.log_level = args.log_level or config.log_level
    if not config.log_file:
        config.log_file = str(output_dir / "autorocq.log")
    
    # Clear existing log file
    if config.log_file:
        log_path = Path(config.log_file)
        if log_path.exists():
            log_path.unlink()
    
    # Setup logging
    global_logger(config.log_level, config.log_file, True)
    logger = setup_logger(name="Main")
    
    logger.info(f"🔧 Log level: {config.log_level}")
    logger.info(f"🔧 Logging to: {config.log_file}")
    logger.info("=== Proof Agent Starting ===")
    logger.info("🗑️  Log file cleared - starting fresh session")
    
    # ADD MODEL LOGGING HERE - right after the starting message
    llm_model = getattr(config.llm, 'model', 'unknown')
    llm_temperature = getattr(config.llm, 'temperature', 'unknown')
    logger.info(f"🤖 LLM Configuration:")
    logger.info(f"   Model: {llm_model}")
    logger.info(f"   Temperature: {llm_temperature}")
    logger.info(f"   Caching: {config.llm.enable_caching}")
    
    # Enhanced proof file logging with full path info
    proof_file_path = Path(config.coq.proof_file_path)
    logger.info(f"📄 Proof File Information:")
    logger.info(f"   File: {proof_file_path.name}")
    logger.info(f"   Full Path: {config.coq.proof_file_path}")
    logger.info(f"   Directory: {proof_file_path.parent}")
    
    logger.info(f"🎯 Target Theorem: {args.theorem or 'auto-detect'}")
    logger.info(f"🔧 Configuration:")
    logger.info(f"   Max steps: {config.coq.max_steps}")
    logger.info(f"   Context search: {config.enable_context_search}")
    logger.info(f"   Output directory: {output_dir}")

    # Log library configuration if present
    if hasattr(config.coq, 'library_paths') and config.coq.library_paths:
        logger.info("📚 Custom libraries configured:")
        for lib_config in config.coq.library_paths:
            logger.info(f"   - {lib_config['name']}: {lib_config['path']}")
    
    if hasattr(config.coq, 'coqproject_extra_options') and config.coq.coqproject_extra_options:
        logger.info("⚙️ Extra CoqProject options:")
        for option in config.coq.coqproject_extra_options:
            logger.info(f"   - {option}")

    # Clean proof by removing existing tactics
    logger.info("🧹 Pre-cleaning proof file to ensure unproven state...")
    clean_success = clean_proof_file(args.proof_file, logger)
    if not clean_success:
        logger.warning("⚠️ Could not clean proof file - will try CoqInterface methods later")

    # Initialize components
    try:
        components = initialize_components(args, config, logger)  # Pass both args and config
        logger.info("✅ Components initialized successfully")
        
        coq_chat_session = components["coq_chat_session"]
        logger.info(f"✅ Coq chat session initialized: {coq_chat_session.model}")
        
        # Log final proof file verification
        coq_interface = components["coq_interface"]
        logger.info(f"✅ Coq interface loaded: {coq_interface.file_path}")
        
        if not clean_success:
            logger.info("🧹 Attempting CoqInterface-based clearing as backup...")
            try:
                proof_status = coq_interface.get_proof_completion_status()
                if proof_status.get('is_complete', False):
                    success = coq_interface.clear_proof_tactics()
                    if success:
                        logger.info("✅ CoqInterface clearing successful")
                    else:
                        logger.warning("⚠️ CoqInterface clearing failed")
                else:
                    success = coq_interface.clear_unproven_proof_steps()
                    if success:
                        logger.info("✅ Cleared unproven steps")
            except Exception as backup_error:
                logger.warning(f"⚠️ Backup clearing failed: {backup_error}")
        
        # Verify we now have an unproven proof to work with
        logger.info("🔍 Verifying proof state after cleaning...")
        proof_ready = False
        try:
            unproven_proof = coq_interface.get_unproven_proof()
            if unproven_proof:
                logger.info(f"✅ Found unproven proof with {len(unproven_proof.steps)} steps")
                
                # Check if we have goals to prove
                goals = coq_interface.get_goal_str()
                if goals and goals != "No current goals" and goals.strip():
                    logger.info(f"✅ Found goals to prove")
                    proof_ready = True
                else:
                    logger.warning("⚠️ No current goals found")
            else:
                logger.error("❌ No unproven proof available after cleaning")
                
        except Exception as verify_error:
            logger.error(f"❌ Error verifying proof state: {verify_error}")
        
        # Exit gracefully if no proof is ready
        if not proof_ready:
            logger.error("❌ Cannot proceed - no unproven proof with goals available")
            logger.error("   Please check the .v file structure")
            logger.error("   File should contain: Theorem name : statement. Proof. Qed.")
            exit_code = 1
            return  # Exit gracefully
        
        print_initial_state(components, logger)
        
        # Run proof attempt
        logger.info("Starting proof attempt...")
        logger.info("=== Starting Proof Attempt ===")
        logger.info(f"Maximum steps allowed: {config.coq.max_steps}")
        
        result = components["controller"].prove_theorem(args.theorem)
        
        if result:
            logger.info("🎉 Proof completed successfully!")
            exit_code = 0
        else:
            logger.warning("❌ Proof incomplete")
            exit_code = 1
            
    except Exception as e:
        logger.error(f"❌ Error during proof attempt: {e}")
        logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    
    finally:
        logger.info("=== Proof Agent Finished ===")
        logger.info(f"📄 Proof file processed: {config.coq.proof_file_path}")
        logger.info(f"🏁 Exit code: {exit_code}")
        
        # Print token statistics
        try:
            logger.info("=== Token Usage Statistics ===")
            stats = components["coq_chat_session"].get_token_statistics()
            
            logger.info(f"📊 API calls: {stats['api_calls']}")
            logger.info(f"📊 Total prompt tokens: {stats['total_prompt_tokens']:,}")
            logger.info(f"📊 Total completion tokens: {stats['total_completion_tokens']:,}")
            logger.info(f"📊 Total cached tokens (read): {stats['total_cached_tokens']:,}")
            logger.info(f"📊 Total cache-write tokens: {stats.get('total_cache_creation_tokens', 0):,}")
            logger.info(f"📊 Total tokens: {stats['total_tokens']:,}")
            logger.info(f"📊 Estimated cost (USD): ${stats.get('total_cost_usd', 0.0):.4f}")
            
            # Calculate cache hit rate
            if stats['total_prompt_tokens'] > 0:
                cache_hit_rate = (stats['total_cached_tokens'] / stats['total_prompt_tokens']) * 100
                logger.info(f"📊 Cache hit rate: {cache_hit_rate:.1f}%")
            
            # Print cost to terminal if not logged
            if logger.getEffectiveLevel() > logging.INFO:
                print(f"📊 API calls: {stats['api_calls']}")
                print(f"📊 Estimated cost (USD): ${stats.get('total_cost_usd', 0.0):.4f}")
                    
        except Exception as e:
            logger.warning(f"Could not retrieve token statistics: {e}")
        
        cleanup_components(components, logger)
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
