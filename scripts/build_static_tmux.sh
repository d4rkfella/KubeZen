#!/bin/bash
set -euo pipefail

# Parse arguments
if [ $# -eq 0 ]; then
    # No arguments provided, use defaults
    TMUX_VERSION="3.5a"
    WORKSPACE_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
elif [ $# -eq 1 ]; then
    # One argument provided - if it looks like a version (contains a dot), it's a version, otherwise it's a workspace path
    if [[ "$1" =~ [0-9]+\.[0-9]+ ]]; then
        TMUX_VERSION="$1"
        WORKSPACE_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    else
        TMUX_VERSION="3.5a"
        # Convert relative path to absolute
        WORKSPACE_PATH="$(cd "$1" && pwd)"
    fi
else
    # Two arguments provided
    TMUX_VERSION="$1"
    # Convert relative path to absolute
    WORKSPACE_PATH="$(cd "$2" && pwd)"
fi

# Set up paths relative to the workspace
OUTPUT_DIR="${WORKSPACE_PATH}/bin"
BUILD_DIR="${WORKSPACE_PATH}/tmux_build"

echo "Building static tmux version: ${TMUX_VERSION}"
echo "Workspace path: ${WORKSPACE_PATH}"
echo "Output will be placed in: ${OUTPUT_DIR}"
echo "Build directory: ${BUILD_DIR}"

# Create output directory and clean build directory
mkdir -p "${OUTPUT_DIR}"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

cleanup() {
    echo "Cleaning up build artifacts..."
    rm -rf "${BUILD_DIR}"
}

# Set up trap to clean up on exit
trap cleanup EXIT

libevent() {
    echo "Building libevent..."
    cd "${BUILD_DIR}"
    curl -LO https://github.com/libevent/libevent/releases/download/release-2.1.12-stable/libevent-2.1.12-stable.tar.gz
    tar -zxvf libevent-2.1.12-stable.tar.gz
    cd libevent-2.1.12-stable
    ./configure --prefix="${BUILD_DIR}/libevent" --enable-static --disable-shared --disable-openssl && make V=1 && make install
    cd "${BUILD_DIR}"
    echo "libevent build completed."
    echo "Checking for libevent.pc..."
    if [ ! -f "${BUILD_DIR}/libevent/lib/pkgconfig/libevent.pc" ]; then
        echo "ERROR: libevent.pc not found after libevent build!"
        ls -l "${BUILD_DIR}/libevent/lib/pkgconfig/"
        exit 1
    fi
    echo "libevent.pc found."
}

ncurses() {
    echo "Building ncurses..."
    cd "${BUILD_DIR}"
    curl -LO https://ftp.gnu.org/pub/gnu/ncurses/ncurses-6.5.tar.gz
    tar zxvf ncurses-6.5.tar.gz
    cd ncurses-6.5
    ./configure --prefix="${BUILD_DIR}/ncurses" \
                --enable-static --disable-shared \
                --with-default-terminfo-dir="${BUILD_DIR}/ncurses/share/terminfo" \
                --with-terminfo-dirs="${BUILD_DIR}/ncurses/share/terminfo" \
                --enable-pc-files \
                --with-pkg-config-libdir="${BUILD_DIR}/ncurses/lib/pkgconfig" \
    && make V=1 && make install
    cd "${BUILD_DIR}"
    echo "ncurses build completed."

    echo "Copying terminfo directory to project resources folder..."
    mkdir -p "${WORKSPACE_PATH}/resources/terminfo"
    cp -r "${BUILD_DIR}/ncurses/share/terminfo/." "${WORKSPACE_PATH}/resources/terminfo/"
    echo "terminfo copied to ${WORKSPACE_PATH}/resources/terminfo/"
}

tmux() {
    echo "Building tmux..."
    cd "${BUILD_DIR}"
    curl -LO "https://github.com/tmux/tmux/releases/download/${TMUX_VERSION}/tmux-${TMUX_VERSION}.tar.gz"
    tar zxvf "tmux-${TMUX_VERSION}.tar.gz"
    cd "tmux-${TMUX_VERSION}"

    export PKG_CONFIG_PATH="${BUILD_DIR}/libevent/lib/pkgconfig:${BUILD_DIR}/ncurses/lib/pkgconfig"
    export CPPFLAGS="-I${BUILD_DIR}/libevent/include -I${BUILD_DIR}/ncurses/include -I${BUILD_DIR}/ncurses/include/ncurses"
    export LDFLAGS="-L${BUILD_DIR}/libevent/lib -L${BUILD_DIR}/ncurses/lib"

    echo "Verifying libevent via pkg-config..."
    pkg-config --exists --print-errors libevent || (echo "pkg-config cannot find libevent. Check PKG_CONFIG_PATH." && exit 1)
    echo "libevent found by pkg-config."

    ./configure --enable-static --prefix="${BUILD_DIR}/tmux_install" && make V=1 && make install
    cd "${BUILD_DIR}"

    mv "${BUILD_DIR}/tmux_install/bin/tmux" "${OUTPUT_DIR}/tmux"
    echo "tmux build completed."
    echo "Static tmux binary is now at ${OUTPUT_DIR}/tmux"
}

libevent
ncurses
tmux

if [ -f "${OUTPUT_DIR}/tmux" ]; then
    echo "✅ Static tmux build successful"
    file "${OUTPUT_DIR}/tmux"  # Show file type to verify it's static
else
    echo "❌ Static tmux build failed - tmux binary not found"
    exit 1
fi
