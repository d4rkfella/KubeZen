#!/bin/bash
set -e

OUTPUT_BASE_DIR="$1"

if [ -z "$OUTPUT_BASE_DIR" ]; then
  echo "Usage: $0 <output_base_directory>"
  exit 1
fi

BIN_DIR="$OUTPUT_BASE_DIR/bin"
mkdir -p "$BIN_DIR"

KUBECTL_LATEST=$(curl -L -s https://dl.k8s.io/release/stable.txt)
echo "Downloading kubectl version ${KUBECTL_LATEST} for linux/amd64..."
curl -Lo "$BIN_DIR/kubectl" "https://dl.k8s.io/release/${KUBECTL_LATEST}/bin/linux/amd64/kubectl"
chmod +x "$BIN_DIR/kubectl"

echo "kubectl downloaded to $BIN_DIR/kubectl"
ls -l "$BIN_DIR/kubectl" 