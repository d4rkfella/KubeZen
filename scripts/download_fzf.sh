#!/bin/bash
set -e

# Check if output directory is provided
if [ -z "$1" ]; then
    echo "Error: Output base directory must be provided"
    echo "Usage: $0 <output_base_dir>"
    exit 1
fi

OUTPUT_BASE_DIR="$1"
FZF_VERSION="0.62.0"

echo "Downloading FZF suite version ${FZF_VERSION}..."

# Create necessary directories
mkdir -p "${OUTPUT_BASE_DIR}/bin"

# Download and extract FZF
echo "Downloading FZF binary..."
curl -fsSLO "https://github.com/junegunn/fzf/releases/download/v${FZF_VERSION}/fzf-${FZF_VERSION}-linux_amd64.tar.gz"
tar xzf "fzf-${FZF_VERSION}-linux_amd64.tar.gz"
mv fzf "${OUTPUT_BASE_DIR}/bin/"
rm "fzf-${FZF_VERSION}-linux_amd64.tar.gz"

# Download fzf-tmux script
echo "Downloading fzf-tmux script..."
curl -fsSLO "https://raw.githubusercontent.com/junegunn/fzf/v${FZF_VERSION}/bin/fzf-tmux" -o "${OUTPUT_BASE_DIR}/bin/fzf-tmux"

echo "FZF suite download complete!"
echo "FZF binary: ${OUTPUT_BASE_DIR}/bin/fzf"
echo "fzf-tmux script: ${OUTPUT_BASE_DIR}/bin/fzf-tmux"
