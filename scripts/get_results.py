#!/usr/bin/env python3
"""
Script to check success status for each proof file in a lemmas list
based on results in proof_statistics.json.
Outputs 1 for success, 0 for failure/not found.

Usage:
    python check_success.py <lemmas_file> <statistics_file>
"""

import argparse
import json
from pathlib import Path


def classify(entry):
    _, success, message, proving_time_seconds = entry
    if message == "Unable to proceed":
        return 'error'
    if proving_time_seconds is not None and proving_time_seconds > 600:
        return '0'
    return '1' if success else '0'


def lookup(file_success_map, candidates):
    """Try each candidate key, then fall back to a linear scan by filename."""
    for key in candidates:
        if key in file_success_map:
            return classify(file_success_map[key])
    # Linear scan: match by filename portion of the map keys
    target = Path(candidates[-1]).name
    for key, entry in file_success_map.items():
        if Path(key).name == target:
            return classify(entry)
    return 'not_found'


def main():
    parser = argparse.ArgumentParser(
        description="Check success status for each proof file based on statistics."
    )
    parser.add_argument("lemmas_file", type=Path, help="Path to the lemmas list file (e.g.,svcomp-ablation.txt)")
    parser.add_argument("statistics_file", type=Path, help="Path to the proof statistics JSON file")
    args = parser.parse_args()

    # Load the statistics JSON
    with open(args.statistics_file, 'r') as f:
        data = json.load(f)
    
    # Build a mapping from file path suffix to success status
    # Use the most recent record (latest session_id) for each file
    file_success_map = {}
    
    for record in data['records']:
        proof_file = record['proof_file']
        session_id = record['session_id']
        success = record['success']
        message = record['completion_message']
        proving_time_seconds = record['proving_time_seconds']
        
        # Extract the filename (no directory path)
        # The filename in statistics is the key for lookup
        filename = Path(proof_file).name
        
        # Keep only the most recent record (higher session_id = more recent)
        if filename not in file_success_map or session_id > file_success_map[filename][0]:
            file_success_map[filename] = (session_id, success, message, proving_time_seconds)
    
    # Read the lemmas file and check each line
    with open(args.lemmas_file, 'r') as f:
        lines = f.readlines()
    
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            results.append('0')
            continue
        
        # Convert "/" to "_" to match the statistics file format
        # e.g., "hex2bin/hex2bin_assert.v" -> "hex2bin_hex2bin_assert.v"
        lookup_key = line.replace('/', '_').replace('-', '_')
        
        filename = Path(line).name
        results.append(lookup(file_success_map, [lookup_key, filename]))
    
    # Output results
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
