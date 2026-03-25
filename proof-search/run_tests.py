#!/usr/bin/env python3
"""
Test runner for the proof-search project.
Discovers and runs all tests to verify the system works correctly.
"""

import sys
import os
import subprocess
import logging
import shutil
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

def setup_logging():
    """Setup logging for the test runner."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def backup_and_clean_example_file(logger):
    """Backup original example.v and create clean version for testing."""
    from tests.test_utils import reset_coq_file_to_admitted
    
    example_file = Path(__file__).parent / "examples" / "example.v"
    
    if not example_file.exists():
        logger.error(f"❌ example.v not found at {example_file}")
        return False
    
    # Reset to Admitted. state and create a backup)
    if reset_coq_file_to_admitted(example_file, backup=True):
        logger.info("✅ Cleaned example.v - reset proof to 'Proof. Admitted.'")
    else:
        logger.warning("⚠️  Could not find proof in example.v to clean")
    
    return True

def restore_example_file(logger):
    """Restore original example.v from backup."""
    from tests.test_utils import restore_coq_file_from_backup, get_example_file
    
    example_file = get_example_file()
    
    if restore_coq_file_from_backup(example_file):
        logger.info("✅ Restored original example.v from backup")
    else:
        logger.warning("⚠️  No backup file found to restore")

def print_test_header(test_name, test_description=""):
    """Print formatted test header."""
    print("\n" + "="*80)
    print(f"🔥 STARTING TEST: {test_name}")
    if test_description:
        print(f"📝 Description: {test_description}")
    print("="*80)

def print_test_footer(test_name, success=True, count_info=None):
    """Print formatted test footer."""
    status = "✅ PASSED" if success else "❌ FAILED"
    
    if count_info:
        test_display = f"{test_name} ({count_info})"
    else:
        test_display = test_name
        
    print("="*80)
    print(f"🏁 FINISHED TEST: {test_display} - {status}")
    print("="*80 + "\n")

def run_single_test_file(logger, test_file):
    """Run a single test file."""
    test_name = test_file.name
    print_test_header(test_name, f"Running {test_file}")
    
    logger.info(f"Running {test_file.name}...")
    
    # Clean example.v before test
    if not backup_and_clean_example_file(logger):
        logger.error(f"Failed to clean example.v for {test_file.name}")
        print_test_footer(test_name, False)
        return False
    
    try:
        # Set up environment with proper Python path
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).parent) + ':' + env.get('PYTHONPATH', '')
        
        # Run with real-time output (no capture) so we can see progress
        # Use a timeout to prevent infinite hangs
        result = subprocess.run(
            [sys.executable, '-u', str(test_file)],  # -u for unbuffered output
            cwd=str(Path(__file__).parent),
            env=env,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode == 0:
            logger.info(f"✅ {test_file.name} PASSED")
            print_test_footer(test_name, True)
            return True
        else:
            logger.error(f"❌ {test_file.name} FAILED (exit code: {result.returncode})")
            print_test_footer(test_name, False)
            return False
    
    except subprocess.TimeoutExpired:
        logger.error(f"⏰ {test_file.name} TIMED OUT after 5 minutes")
        print_test_footer(test_name, False)
        return False
            
    except Exception as e:
        logger.error(f"Error running {test_file.name}: {e}")
        print_test_footer(test_name, False)
        return False
    
    finally:
        # Restore example.v after test
        restore_example_file(logger)

def run_all_custom_tests(logger, test_files):
    """Run all custom test files."""
    total_tests = len(test_files)
    print_test_header("ALL CUSTOM TESTS", f"Running all {total_tests} test files")
    
    all_passed = True
    passed_count = 0
    
    for i, test_file in enumerate(test_files, 1):
        print(f"\n{'+'*60}")
        print(f"🧪 Running Test {i}/{total_tests}: {test_file.name}")
        print(f"{'+'*60}")
        
        if run_single_test_file(logger, test_file):
            passed_count += 1
        else:
            all_passed = False
        
        print(f"{'+'*60}")
    
    # Show the count in the footer
    count_info = f"{passed_count}/{total_tests}"
    print_test_footer("ALL CUSTOM TESTS", all_passed, count_info)
    return all_passed

def check_dependencies(logger):
    """Check if required dependencies are available."""
    logger.info("Checking dependencies...")
    
    # Check for Coq installation first
    try:
        result = subprocess.run(['coqtop', '-v'], capture_output=True, text=True)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            logger.info(f"✅ Coq is available: {version_line}")
        else:
            logger.error("❌ Coq is not properly installed")
            return False
    except FileNotFoundError:
        logger.error("❌ Coq is not installed or not in PATH")
        return False
    
    # Check optional modules
    optional_modules = [
        ('coqpyt', 'CoqPyt integration'),
        ('pytest', 'PyTest framework')
    ]
    
    for module, description in optional_modules:
        try:
            __import__(module)
            logger.info(f"✅ {module} is available ({description})")
        except ImportError:
            logger.warning(f"⚠️  {module} is missing ({description}) - some tests may be skipped")
    
    return True

def show_test_menu(test_files):
    """Display test selection menu with dynamically numbered test files."""
    print("\n" + "🧪 TEST SUITE MENU" + "\n" + "="*60)
    print("0 Run ALL test files")
    
    for i, test_file in enumerate(test_files, 1):
        print(f"{i}  {test_file.name}")
    
    print("="*60)

def get_user_choice(max_choice):
    """Get user's test selection."""
    while True:
        try:
            choice = input(f"\n🔍 Select test to run (0-{max_choice}): ").strip()
            if choice.isdigit() and 0 <= int(choice) <= max_choice:
                return int(choice)
            else:
                print(f"❌ Invalid choice. Please enter a number between 0 and {max_choice}.")
        except (ValueError, KeyboardInterrupt):
            print("\n👋 Exiting...")
            sys.exit(0)

def main():
    """Main test runner function."""
    logger = setup_logging()
    
    print("🚀 " + "="*60)
    print("🚀 PROOF-SEARCH TEST SUITE")
    print("🚀 " + "="*60)
    
    # Check dependencies first
    if not check_dependencies(logger):
        logger.error("❌ Critical dependency check failed")
        return 1
    
    # Discover test files dynamically
    tests_dir = Path(__file__).parent / "tests"
    if not tests_dir.exists():
        logger.error(f"❌ Tests directory not found: {tests_dir}")
        return 1
    
    test_files = sorted(list(tests_dir.glob("test_*.py")))
    if not test_files:
        logger.error("❌ No test files found in tests/ directory")
        return 1
    
    # Show menu and get user choice
    show_test_menu(test_files)
    choice = get_user_choice(len(test_files))
    
    # Execute selected test(s)
    if choice == 0:
        print(f"\n🎯 Running ALL {len(test_files)} test files...")
        success = run_all_custom_tests(logger, test_files)
    else:
        selected_test = test_files[choice - 1]
        print(f"\n🎯 Running selected test: {selected_test.name}")
        success = run_single_test_file(logger, selected_test)
    
    # Final summary
    print("\n" + "🏆 " + "="*60)
    print("🏆 FINAL TEST RESULTS")
    print("🏆 " + "="*60)
    if success:
        print("🎉 SELECTED TEST(S) PASSED!")
        print("🏆 " + "="*60 + "\n")
        return 0
    else:
        print("💥 SELECTED TEST(S) FAILED!")
        print("🏆 " + "="*60 + "\n")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)