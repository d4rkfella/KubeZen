#!/bin/bash

LOG_FILE=$(tmux display -p -t "$TMUX_PANE" "#{@logfile}")
if [[ -z "$LOG_FILE" || ! -f "$LOG_FILE" ]]; then
    exit 0
fi

if ! command -v fzf >/dev/null 2>&1; then
    echo "Error: fzf not found in PATH"
    exit 1
fi

# --- Main logic ---
SELECTED_LINE=$(nl -ba -w1 "$LOG_FILE" | fzf \
    --tmux="center,80%,60%" \
    --ansi \
    --layout=reverse-list \
    --preview "echo {}" \
    --preview-window=up:1,wrap \
    --bind "enter:accept" \
    --bind "f2:abort")

if [[ -n "$SELECTED_LINE" ]]; then
    LINE_NO=$(echo "$SELECTED_LINE" | awk '{sub(/^[ \t]+/, ""); print $1}')
    tmux send-keys -t "$TMUX_PANE" "$LINE_NO"
    tmux send-keys -t "$TMUX_PANE" "g"
fi
