#!/usr/bin/env python3

import sys
from collections import defaultdict
import re

class ProfileEntry:
    def __init__(self, module, function, ncalls=0, tsub=0.0):
        self.module = module
        self.name = function
        self.ncall = ncalls
        self.tsub = tsub  # time in seconds

def format_time_per_call(tsub, ncall):
    """Safely format time per call, handling zero calls case"""
    if ncall > 0:
        return f"{(tsub/ncall)*1000:.3f}"
    return "N/A"

def parse_profile(filename):
    entries = []
    file_map = {}  # Maps file IDs to file paths
    current_file = None
    current_func = None
    
    with open(filename) as f:
        # Skip header until events line
        for line in f:
            if line.startswith('events:'):
                break
        
        # Process the rest of the file
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # File definition
            if line.startswith('fl='):
                match = re.match(r'fl=\((\d+)\) (.+)', line)
                if match:
                    file_id, file_path = match.groups()
                    file_map[file_id] = file_path
                    current_file = file_path
            
            # Function definition
            elif line.startswith('fn='):
                match = re.match(r'fn=\((\d+)\) (.+)', line)
                if match:
                    func_id, func_name = match.groups()
                    current_func = func_name
                    # Create new entry
                    if current_file:
                        entries.append(ProfileEntry(current_file, current_func))
            
            # Cost line (calls and time)
            elif current_file and current_func and not line.startswith(('cfl=', 'cfn=')):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        calls = int(parts[0])
                        time = float(parts[1])  # This is in ticks
                        # Find the most recent entry for this function
                        for entry in reversed(entries):
                            if entry.name == current_func and entry.module == current_file:
                                entry.ncall += calls
                                entry.tsub += time
                                break
                    except (ValueError, IndexError):
                        pass

    # Convert ticks to seconds (assuming ticks are microseconds)
    for entry in entries:
        entry.tsub /= 1_000_000

    # Filter out entries with empty names or modules and zero calls
    entries = [e for e in entries if e.name and e.module and e.ncall > 0]

    # Sort entries
    entries_by_time = sorted(entries, key=lambda x: x.tsub, reverse=True)
    entries_by_calls = sorted(entries, key=lambda x: x.ncall, reverse=True)

    # Print file frequency analysis
    print("\nMost frequently appearing files:")
    file_counts = defaultdict(int)
    for entry in entries:
        file_counts[entry.module] += 1
    
    for file, count in sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f" {count:3d} {file}")

    # Print top functions by total time
    print("\nTop 50 functions by total time:")
    print(f"{'Total Time (s)':>12} {'Calls':>8} {'Time/Call (ms)':>14} {'Function Name':<50} {'Module'}")
    print("-" * 100)
    
    for entry in entries_by_time[:50]:
        time_per_call = format_time_per_call(entry.tsub, entry.ncall)
        name = entry.name[:47] + "..." if len(entry.name) > 50 else entry.name.ljust(50)
        print(f"{entry.tsub:12.3f} {entry.ncall:8d} {time_per_call:>14} {name} {entry.module}")

    # Print top functions by number of calls
    print("\nTop 50 functions by number of calls:")
    print(f"{'Calls':>8} {'Total Time (s)':>12} {'Time/Call (ms)':>14} {'Function Name':<50} {'Module'}")
    print("-" * 100)
    
    for entry in entries_by_calls[:50]:
        time_per_call = format_time_per_call(entry.tsub, entry.ncall)
        name = entry.name[:47] + "..." if len(entry.name) > 50 else entry.name.ljust(50)
        print(f"{entry.ncall:8d} {entry.tsub:12.3f} {time_per_call:>14} {name} {entry.module}")

    # Print details for top time-consuming functions
    print("\nDetails for top 5 time-consuming functions:")
    print("-" * 100)
    
    for entry in entries_by_time[:5]:
        print(f"\nFunction: {entry.name}")
        print(f"Module: {entry.module}")
        print(f"Total time: {entry.tsub:.3f}s")
        print(f"Total calls: {entry.ncall}")
        print(f"Average time per call: {format_time_per_call(entry.tsub, entry.ncall)}ms")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <profile_file>")
        sys.exit(1)
    
    parse_profile(sys.argv[1]) 