#!/bin/bash
set -euo pipefail

# Parse arguments
if [ $# -eq 0 ]; then
    # No arguments provided, use defaults
    VIM_VERSION="v9.1.1415"
    WORKSPACE_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
elif [ $# -eq 1 ]; then
    # One argument provided - if it starts with 'v', it's a version, otherwise it's a workspace path
    if [[ "$1" =~ ^v[0-9] ]]; then
        VIM_VERSION="$1"
        WORKSPACE_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    else
        VIM_VERSION="v9.1.1415"
        WORKSPACE_PATH="$1"
    fi
else
    # Two arguments provided
    VIM_VERSION="$1"
    WORKSPACE_PATH="$2"
fi

# Set up paths relative to the workspace
OUTPUT_DIR="${WORKSPACE_PATH}/bin"

echo "Building static Vim version: ${VIM_VERSION}"
echo "Workspace path: ${WORKSPACE_PATH}"
echo "Output will be placed in: ${OUTPUT_DIR}"

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Set up Docker volume mount to output directory
DOCKER_VOLUME="${OUTPUT_DIR}:/out"
echo "Using Docker volume mount: ${DOCKER_VOLUME}"

docker run -i --rm \
    -v "${DOCKER_VOLUME}" \
    -w /root \
    alpine /bin/sh <<EOF
apk add gcc make musl-dev ncurses-static git
wget "https://github.com/vim/vim/archive/refs/tags/${VIM_VERSION}.tar.gz" -O "vim-${VIM_VERSION}.tar.gz"
tar xvfz "vim-${VIM_VERSION}.tar.gz"
cd "vim-${VIM_VERSION#v}"  # Remove 'v' prefix from version for directory name
LDFLAGS="-static" ./configure \
    --disable-channel \
    --disable-gpm \
    --disable-gtktest \
    --disable-gui \
    --disable-netbeans \
    --disable-nls \
    --disable-selinux \
    --disable-smack \
    --disable-sysmouse \
    --disable-xsmp \
    --enable-multibyte \
    --with-features=huge \
    --without-x \
    --with-tlib=ncursesw
make
make install
mkdir -p /out
cp /usr/local/bin/vim /out/vim
strip /out/vim
chown -R $(id -u):$(id -g) /out
EOF

# Verify the build
if [ -f "${OUTPUT_DIR}/vim" ]; then
    echo "✅ Static Vim build successful"
    file "${OUTPUT_DIR}/vim"  # Show file type to verify it's static
else
    echo "❌ Static Vim build failed - vim binary not found"
    exit 1
fi