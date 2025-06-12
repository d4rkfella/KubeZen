#!/usr/bin/env python3
"""
A simple, efficient script to read a data file and print its contents to stdout.
This is intended to be called by fzf's `reload` action to populate its item list
from a data file, avoiding the need for complex shell scripting with heredocs.
"""
import sys
from pathlib import Path

def main():
    """Main entry point of the script."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <data_file>", file=sys.stderr)
        sys.exit(1)

    data_file = Path(sys.argv[1])
    if not data_file.is_file():
        # In the context of fzf reloads, the file may have been cleaned up
        # by a previous action. This is not necessarily a hard error.
        # Exiting gracefully without output is the correct behavior.
        sys.exit(0)

    try:
        # Read all lines at once to ensure we don't get partial reads
        with data_file.open('r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # Remove any duplicates while preserving order
        seen = set()
        unique_lines = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)
                
        # Write all lines at once to avoid interleaving
        sys.stdout.writelines(unique_lines)
    except Exception as e:
        # If an error occurs, log it to stderr so it doesn't pollute
        # fzf's item list.
        print(f"Error reading data file {data_file}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main() 