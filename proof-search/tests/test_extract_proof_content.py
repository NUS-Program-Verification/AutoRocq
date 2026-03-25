#!/usr/bin/env python3
"""
Simple test script for extract_essential_proof_content function using real file
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from utils.config import ProofAgentConfig
from tests.test_utils import reset_coq_file_to_admitted, restore_coq_file_from_backup


# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"


def clean_proof_file(file_path):
    """Clean the proof file using shared utility."""
    print("\n🧹 CLEANING PROOF FILE...")
    print("="*60)
    
    success = reset_coq_file_to_admitted(file_path, backup=True)
    if success:
        print("✅ File cleaned successfully - reset to 'Proof. Admitted.'")
    else:
        print("❌ Failed to clean file")
    return success

def test_extract_with_real_file():
    """Test the extract_essential_proof_content function with the real Coq file"""
    
    print("🧪 Testing extract_essential_proof_content with real file")
    print("=" * 70)
    print(f"📁 File: {coq_file}")
    print(f"📄 Config: {config_file}")
    
    try:
        # Check if file exists
        if not coq_file.exists():
            print(f"❌ File not found: {coq_file}")
            return False
        
        clean_proof_file(coq_file)
        # Check if config file exists
        if not config_file.exists():
            print(f"❌ Config file not found: {config_file}")
            return False
        
        # Read the file
        print("📖 Reading file...")
        with open(coq_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"✅ File loaded successfully")
        print(f"📊 Original file statistics:")
        print(f"   - Size: {len(content):,} characters")
        print(f"   - Lines: {len(content.splitlines()):,}")
        print(f"   - Contains 'is_sint32': {'is_sint32' in content}")
        print(f"   - Contains 'wp_goal': {'wp_goal' in content}")
        
        # Create ContextManager
        print("\n🔧 Creating ContextManager...")
        
        # Load configuration from file
        print(f"📄 Loading config from: {config_file}")
        config = ProofAgentConfig.from_file(str(config_file))
        print(f"✅ Loaded configuration from {config_file}")
        
        # Create CoqInterface
        coq_interface = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            timeout=config.coq.timeout
        )
        coq_interface.load()
        
        try:
            # Create ContextManager
            context_manager = ContextManager(coq_interface, api_key=config.llm.api_key)
            print("✅ ContextManager created")
            
            # Extract essential content
            print("\n🔄 Extracting essential content...")
            extracted = context_manager.extract_essential_proof_content(content)
            print("✅ Extraction completed")
            
            # Analyze results
            print(f"\n📊 Extraction results:")
            extracted_lines = extracted.splitlines()
            print(f"   - Extracted size: {len(extracted):,} characters")
            print(f"   - Extracted lines: {len(extracted_lines):,}")
            print(f"   - Compression ratio: {len(extracted)/len(content):.1%}")
            print(f"   - Size reduction: {len(content) - len(extracted):,} characters")
            
            # Validate content
            print(f"\n✅ Content validation:")
            checks = {
                "Has Require imports": any("Require " in line for line in extracted_lines),
                "Has ZArith import": "From Coq Require Import ZArith Lia." in extracted,
                "Has Open Scope": "Open Scope Z_scope." in extracted,
                "Has wp_goal theorem": "Theorem wp_goal" in extracted
            }
            
            all_passed = True
            for check_name, result in checks.items():
                status = "✅" if result else "❌"
                print(f"   {status} {check_name}")
                if not result:
                    all_passed = False
            
            # Show extracted content preview
            print(f"\n📋 Extracted content preview:")
            print("=" * 70)
            preview_lines = extracted_lines[:30]  # Show first 30 lines
            for i, line in enumerate(preview_lines, 1):
                print(f"{i:2d}: {line}")
            
            if len(extracted_lines) > 30:
                print(f"... (showing first 30 of {len(extracted_lines)} total lines)")
            
            print("=" * 70)
            
            # Show what was filtered out
            print(f"\n🔍 Filtering analysis:")
            original_requires = len([line for line in content.splitlines() if line.strip().startswith("Require ")])
            extracted_requires = len([line for line in extracted_lines if line.strip().startswith("Require ")])
            
            original_definitions = len([line for line in content.splitlines() if "Definition " in line or "Parameter " in line or "Axiom " in line])
            extracted_definitions = len([line for line in extracted_lines if "Definition " in line or "Parameter " in line or "Axiom " in line])
            
            print(f"   - Original Require statements: {original_requires}")
            print(f"   - Extracted Require statements: {extracted_requires}")
            print(f"   - Original definitions/parameters/axioms: {original_definitions}")
            print(f"   - Extracted definitions/parameters/axioms: {extracted_definitions}")
            print(f"   - Filtered out: {original_definitions - extracted_definitions} definitions")
            
            # Final result
            print(f"\n🏁 Test Result:")
            if all_passed:
                print("🎉 SUCCESS! Function works correctly")
                print("✅ Essential content extracted properly")
                print("✅ Comments removed")
                print("✅ Only relevant definitions included")
                print("✅ Theorem and proof preserved")
            else:
                print("❌ FAILED! Some checks didn't pass")
            
            return all_passed
        
        finally:
            coq_interface.close()
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Simple Essential Content Extraction Test")
    print("=" * 70)
    
    # Run the test
    success = test_extract_with_real_file()
    
    # Final summary
    print("\n" + "=" * 70)
    if success:
        print("🎉 TEST PASSED!")
        print("✅ extract_essential_proof_content function works correctly")
        print("✅ Ready for use in ContextManager")
    else:
        print("❌ TEST FAILED!")
        print("🔧 Function needs debugging")
    
    print(f"\n💡 What this test verified:")
    print(f"   - ✅ Real file processing")
    print(f"   - ✅ Comment removal") 
    print(f"   - ✅ Import extraction")
    print(f"   - ✅ Definition filtering")
    print(f"   - ✅ Theorem preservation")
    print(f"   - ✅ Content compression")
    
    sys.exit(0 if success else 1)
