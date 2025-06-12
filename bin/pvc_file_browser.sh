#!/bin/bash
#
# This script launches a kubectl port-forward session for a temporary pod
# and ensures the pod is cleaned up when the script exits.
#

set -e

# Check for the correct number of arguments
if [ "$#" -ne 4 ]; then
    echo "Usage: $0 <NAMESPACE> <POD_NAME> <LOCAL_PORT> <PVC_NAME>" >&2
    exit 1
fi

NAMESPACE="$1"
POD_NAME="$2"
LOCAL_PORT="$3"
PVC_NAME="$4"

# Define the cleanup function that will be called on exit
cleanup() {
    echo ""
    echo "--- Cleaning up pod ${POD_NAME} in namespace ${NAMESPACE}... ---"
    kubectl delete pod --namespace "${NAMESPACE}" "${POD_NAME}" --ignore-not-found=true
    echo "--- Cleanup complete. ---"
}

# Set the trap to call the cleanup function when the script exits for any reason
trap cleanup EXIT

# The main command to run
main_command="kubectl port-forward --namespace ${NAMESPACE} pod/${POD_NAME} ${LOCAL_PORT}:80"

# Announce what we're doing
echo "--- Preparing File Browser for PVC: ${PVC_NAME} ---"
echo "--- Pod: ${POD_NAME}, Namespace: ${NAMESPACE} ---"
echo "--- Forwarding pod port 80 to local port ${LOCAL_PORT} ---"
echo ""
echo "Click to open in browser: http://localhost:${LOCAL_PORT}"
echo ""
echo "--- This window will automatically clean up on exit. Press Ctrl+C to stop. ---"
echo ""
echo "Attempting to connect..."

sleep 5
# Loop until port-forward succeeds, as the pod might need a moment to be ready
while true; do
  # The '-n 0' check for `ps` is a trick to see if the parent process is still alive.
  # If the parent (the tmux window) is closed, this will fail, and the trap will run.
  if ! ps -p $$ > /dev/null; then
      exit
  fi
  
  if ${main_command}; then
    break
  fi
  
  echo "Port-forward failed. Is the pod ready? Retrying in 2 seconds..."
  sleep 2
done 