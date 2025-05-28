#!/bin/bash
set -euo pipefail

# Default Vim version if not specified
VIM_VERSION="${1:-v9.1.1415}"

# Get the absolute path to the project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/vim_static_build"

echo "Building static Vim version: ${VIM_VERSION}"
echo "Output will be placed in: ${OUTPUT_DIR}"

# Create output directory if it doesn't exist
mkdir -p "${OUTPUT_DIR}"

# Check if we're running in GitHub Actions
if [ -n "${GITHUB_WORKSPACE:-}" ]; then
    # In GitHub Actions, we need to use the workspace path
    DOCKER_VOLUME="${GITHUB_WORKSPACE}/vim_static_build:/out"
else
    # Local development
    DOCKER_VOLUME="${OUTPUT_DIR}:/out"
fi

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
cp -r /usr/local/* /out
strip /out/bin/vim
chown -R $(id -u):$(id -g) /out
echo "Static vim build complete. Files in ${OUTPUT_DIR}"
EOF

# Verify the build
if [ -f "${OUTPUT_DIR}/bin/vim" ]; then
    echo "✅ Static Vim build successful"
    file "${OUTPUT_DIR}/bin/vim"  # Show file type to verify it's static
else
    echo "❌ Static Vim build failed - vim binary not found"
    exit 1
fi 