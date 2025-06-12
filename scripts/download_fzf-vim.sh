#!/bin/bash

# Determine the root directory of the project
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# Define the assets directory
ASSETS_DIR="$PROJECT_ROOT/assets"
FZF_BASE_DIR="$ASSETS_DIR/fzf_base_plugin"  # For junegunn/fzf (base fzf plugin)
FZF_VIM_DIR="$ASSETS_DIR/fzf_vim_plugin"   # For junegunn/fzf.vim (commands plugin)

# --- Setup for junegunn/fzf (BASE fzf plugin) ---
echo "Setting up fzf_base_plugin (from junegunn/fzf)..."
mkdir -p "$FZF_BASE_DIR/plugin"

# Download ONLY plugin/fzf.vim from junegunn/fzf repository
# This file defines fzf#run() and other core functionalities.
# The base junegunn/fzf repository does NOT have an autoload/fzf.vim for its Vimscript.
echo "Downloading junegunn/fzf plugin/fzf.vim..."
curl -fsSL https://raw.githubusercontent.com/junegunn/fzf/master/plugin/fzf.vim -o "$FZF_BASE_DIR/plugin/fzf.vim"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to download base fzf plugin/fzf.vim. Exiting."
    exit 1
fi
echo "fzf_base_plugin (junegunn/fzf plugin/fzf.vim) setup complete."

# --- Setup for junegunn/fzf.vim (COMMANDS fzf.vim plugin) ---
echo "Setting up fzf_vim_plugin (from junegunn/fzf.vim)..."
# Clean directory before cloning to ensure freshness
if [ -d "$FZF_VIM_DIR" ]; then
    echo "Cleaning existing fzf_vim_plugin directory: $FZF_VIM_DIR"
    rm -rf "$FZF_VIM_DIR"
fi
mkdir -p "$FZF_VIM_DIR" # Ensure it exists after potential rm -rf

echo "Cloning junegunn/fzf.vim into $FZF_VIM_DIR..."
git clone --depth 1 https://github.com/junegunn/fzf.vim.git "$FZF_VIM_DIR"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to clone junegunn/fzf.vim.git. Exiting."
    exit 1
fi
echo "fzf_vim_plugin cloned."

# Remove unnecessary files from the cloned fzf.vim repository
echo "Cleaning up unnecessary files from fzf_vim_plugin..."
CURRENT_DIR=$(pwd)
cd "$FZF_VIM_DIR"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to cd into $FZF_VIM_DIR. Cleanup skipped."
else
    rm -rf .git README.md LICENSE screenshots test .github .gitignore .gitattributes
    cd "$CURRENT_DIR"
fi
echo "fzf_vim_plugin cleanup complete."

echo "Full KubeZen assets setup complete."