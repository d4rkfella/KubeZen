#!/bin/bash
# This script is executed by tmux only when the main application crashes.
# It displays a clear message and holds the pane open so the user can see
# the full traceback from the crashed application.

# Print a separator line
echo -e "\n\033[1;31m=== KubeZen Crashed ===\033[0m\n"

# Try to get the last error from the log file
if [ -f "$HOME/KubeZen/kubezen.log" ]; then
    # First, show the immediate error message
    ERROR_MSG=$(grep -B 1 -A 5 "ERROR\|CRITICAL" "$HOME/KubeZen/kubezen.log" | tail -n 10)
    if [ ! -z "$ERROR_MSG" ]; then
        echo -e "\033[1;31mError details:\033[0m"
        echo "$ERROR_MSG"
        echo
    fi

    # Then show the full traceback if it exists
    TRACEBACK=$(grep -A 20 "Traceback" "$HOME/KubeZen/kubezen.log" | tail -n 25)
    if [ ! -z "$TRACEBACK" ]; then
        echo -e "\033[1;31mFull traceback:\033[0m"
        echo "$TRACEBACK"
        echo
    fi
fi

echo -e "\033[1mPress ENTER or wait 30 seconds to close this pane.\033[0m"
echo -e "\033[1mTo copy text: Press Ctrl-B [ to enter copy mode, then use mouse or keyboard to select text.\033[0m"
echo -e "\033[1mIn copy mode: Use arrow keys to move, press Space to start selection, Enter to copy, q to exit copy mode.\033[0m"

# Debug output
echo -e "\nDebug info:"
echo "KUBEZEN_SOCKET_PATH=$KUBEZEN_SOCKET_PATH"
echo "Current tmux socket: $TMUX"

# Set up a key binding for Enter
if [ ! -z "$KUBEZEN_SOCKET_PATH" ]; then
    tmux -S "$KUBEZEN_SOCKET_PATH" bind-key -n Enter run-shell "tmux -S $KUBEZEN_SOCKET_PATH kill-pane"
    # Wait for either Enter or timeout
    tmux -S "$KUBEZEN_SOCKET_PATH" wait-for crash_wait || true
    sleep 30
    tmux -S "$KUBEZEN_SOCKET_PATH" kill-pane
else
    tmux bind-key -n Enter run-shell "tmux kill-pane"
    # Wait for either Enter or timeout
    tmux wait-for crash_wait || true
    sleep 30
    tmux kill-pane
fi

exit 0
