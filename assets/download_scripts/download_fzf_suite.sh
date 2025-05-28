#!/bin/bash
set -e

OUTPUT_BASE_DIR="$1"

if [ -z "$OUTPUT_BASE_DIR" ]; then
  echo "Usage: $0 <output_base_directory>"
  exit 1
fi

BIN_DIR="$OUTPUT_BASE_DIR/bin"
# This directory is where fzf.vim and the fzf runtime files (like shell scripts) will be placed
# So that KubeZen.spec can pick them up from KubeZen/assets/fzf_vim_plugin/
FZF_VIM_PLUGIN_SRC_DIR="$OUTPUT_BASE_DIR/assets_src/fzf_vim_plugin"

mkdir -p "$BIN_DIR"
mkdir -p "$FZF_VIM_PLUGIN_SRC_DIR"
mkdir -p "$FZF_VIM_PLUGIN_SRC_DIR/plugin" # for fzf.vim
mkdir -p "$FZF_VIM_PLUGIN_SRC_DIR/fzf"    # for fzf runtime files (shell, autoload)

# Get latest fzf release URL for linux_amd64
FZF_LATEST_RELEASE_URL=$(curl -s https://api.github.com/repos/junegunn/fzf/releases/latest | grep "browser_download_url.*linux_amd64.tar.gz" | cut -d '"' -f 4)

if [ -z "$FZF_LATEST_RELEASE_URL" ]; then
  echo "Could not determine latest fzf release URL for linux_amd64." >&2
  exit 1
fi

echo "Downloading latest fzf release from $FZF_LATEST_RELEASE_URL..."
TEMP_FZF_DIR=$(mktemp -d)
curl -L "$FZF_LATEST_RELEASE_URL" | tar -xz -C "$TEMP_FZF_DIR"

# Copy fzf binary
echo "Extracting fzf binary..."
cp "$TEMP_FZF_DIR/fzf" "$BIN_DIR/fzf"
chmod +x "$BIN_DIR/fzf"

# Copy Vim plugin files (main plugin script and runtime files)
# The tarball contains `plugin/fzf.vim`, `autoload/fzf.vim`, `shell/` etc.
# We want to reconstruct a structure that vim can use in its runtimepath.

echo "Extracting fzf Vim plugin files..."
if [ -f "$TEMP_FZF_DIR/plugin/fzf.vim" ]; then
    cp "$TEMP_FZF_DIR/plugin/fzf.vim" "$FZF_VIM_PLUGIN_SRC_DIR/plugin/fzf.vim"
else
    echo "Warning: $TEMP_FZF_DIR/plugin/fzf.vim not found in fzf release tarball." >&2
fi

# Copy the autoload directory into the fzf runtime target
if [ -d "$TEMP_FZF_DIR/autoload" ]; then
    cp -r "$TEMP_FZF_DIR/autoload" "$FZF_VIM_PLUGIN_SRC_DIR/fzf/"
else
    echo "Warning: $TEMP_FZF_DIR/autoload directory not found in fzf release tarball." >&2
fi

# Some fzf versions might also have shell scripts or other things fzf.vim might use from the root of the .tar.gz
# For now, we assume `plugin/fzf.vim` and `autoload/` are the main components needed for the Vim plugin part
# The `fzf` binary itself handles its own shell integrations if called directly.

# Download fzf-tmux script
# This script is typically found in the fzf repository's bin directory, not in the release tarball.
echo "Downloading fzf-tmux script..."
FZF_TMUX_URL="https://raw.githubusercontent.com/junegunn/fzf/master/bin/fzf-tmux"
curl -Lo "$BIN_DIR/fzf-tmux" "$FZF_TMUX_URL"
chmod +x "$BIN_DIR/fzf-tmux"

rm -rf "$TEMP_FZF_DIR"

echo "fzf binary downloaded to $BIN_DIR/fzf"
ls -l "$BIN_DIR/fzf"
echo "fzf Vim plugin files placed in $FZF_VIM_PLUGIN_SRC_DIR"
ls -lR "$FZF_VIM_PLUGIN_SRC_DIR"
echo "fzf-tmux script downloaded to $BIN_DIR/fzf-tmux"
ls -l "$BIN_DIR/fzf-tmux" 