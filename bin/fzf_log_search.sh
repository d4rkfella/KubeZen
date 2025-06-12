#!/bin/bash
#
# Wrapper script to perform an fzf search on a log file and jump to the selected line in a tmux pane.
# This script is designed to be called from tmux's 'run-shell' command.
#

# --- Argument and Environment Validation ---
if [[ $# -ne 2 ]]; then
    echo "Usage: $(basename "$0") <log_file_path> <target_pane_id>" >&2
    exit 1
fi

LOG_FILE="$1"
TARGET_PANE="$2"

# --- Find the fzf-tmux script ---
# Assumes 'fzf-tmux' is in the same directory as this script.
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
FZF_TMUX_SCRIPT="$SCRIPT_DIR/fzf-tmux"

if [[ ! -x "$FZF_TMUX_SCRIPT" ]]; then
    echo "Error: fzf-tmux script not found or not executable at '$FZF_TMUX_SCRIPT'" >&2
    exit 1
fi

# --- Main Logic ---
# 1. 'nl' adds line numbers to the log file.
# 2. The result is piped to 'fzf-tmux' for interactive selection.
# 3. 'awk' extracts just the line number from the selected line.
# 4. 'tmux send-keys' sends the line number and the 'g' key to the original pane,
#    which tells 'less' to jump to that line.
SELECTED_LINE=$(nl -ba -w1 "$LOG_FILE" | "$FZF_TMUX_SCRIPT" -p 80% --layout=reverse-list --bind 'load:pos(1)' --preview "echo {}" --preview-window=up:1,wrap --bind "enter:accept" --bind "f2:abort")

if [[ -n "$SELECTED_LINE" ]]; then
    LINE_NO=$(echo "$SELECTED_LINE" | awk '{sub(/^[ \t]+/, ""); print $1}')
    # Send keys to the *explicitly provided* pane where `less` is running.
    tmux send-keys -t "$TARGET_PANE" "$LINE_NO"
    tmux send-keys -t "$TARGET_PANE" "g"
fi
