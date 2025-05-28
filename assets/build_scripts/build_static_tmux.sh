#!/bin/bash
set -euo pipefail

TMUX_VERSION="${1:-3.3a}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/bin"

echo "Building static tmux version: ${TMUX_VERSION}"
echo "Output will be placed in: ${OUTPUT_DIR}"

mkdir -p "${OUTPUT_DIR}"

echo "Cleaning up previous build directories..."
rm -rf libevent-2.1.12-stable ncurses-6.5 "tmux-${TMUX_VERSION}"

libevent() {
  echo "Building libevent..."
  curl -LO https://github.com/libevent/libevent/releases/download/release-2.1.12-stable/libevent-2.1.12-stable.tar.gz
  tar -zxvf libevent-2.1.12-stable.tar.gz
  cd libevent-2.1.12-stable
  ./configure --prefix="${OUTPUT_DIR}" --enable-static --disable-shared --disable-openssl && make V=1 && make install
  cd ..
  echo "libevent build completed."
  echo "Checking for libevent.pc..."
  if [ ! -f "${OUTPUT_DIR}/lib/pkgconfig/libevent.pc" ]; then
    echo "ERROR: libevent.pc not found after libevent build!"
    ls -l "${OUTPUT_DIR}/lib/pkgconfig/"
    exit 1
  fi
  echo "libevent.pc found."
}

ncurses() {
  echo "Building ncurses..."
  curl -LO https://ftp.gnu.org/pub/gnu/ncurses/ncurses-6.5.tar.gz
  tar zxvf ncurses-6.5.tar.gz
  cd ncurses-6.5
  ./configure --prefix="${OUTPUT_DIR}" \
              --enable-static --disable-shared \
              --with-default-terminfo-dir="${OUTPUT_DIR}/share/terminfo" \
              --with-terminfo-dirs="${OUTPUT_DIR}/share/terminfo" \
              --enable-pc-files \
              --with-pkg-config-libdir="${OUTPUT_DIR}/lib/pkgconfig" \
  && make V=1 && make install
  cd ..
  echo "ncurses build completed."
}

tmux() {
  echo "Building tmux..."
  curl -LO "https://github.com/tmux/tmux/releases/download/${TMUX_VERSION}/tmux-${TMUX_VERSION}.tar.gz"
  tar zxvf "tmux-${TMUX_VERSION}.tar.gz"
  cd "tmux-${TMUX_VERSION}"
  
  export PKG_CONFIG_PATH="${OUTPUT_DIR}/lib/pkgconfig"
  export CPPFLAGS="-I${OUTPUT_DIR}/include -I${OUTPUT_DIR}/include/ncurses"
  export LDFLAGS="-L${OUTPUT_DIR}/lib"
  
  echo "Verifying libevent via pkg-config..."
  pkg-config --exists --print-errors libevent || (echo "pkg-config cannot find libevent. Check PKG_CONFIG_PATH." && exit 1)
  echo "libevent found by pkg-config."
  
  ./configure --enable-static --prefix="${OUTPUT_DIR}" && make V=1 && make install
  cd ..
  echo "tmux build completed."
  echo "Static tmux binary is now at ${OUTPUT_DIR}/bin/tmux"
}

libevent
ncurses
tmux

if [ -f "${OUTPUT_DIR}/bin/tmux" ]; then
    echo "✅ Static tmux build successful"
    file "${OUTPUT_DIR}/bin/tmux"  # Show file type to verify it's static
else
    echo "❌ Static tmux build failed - tmux binary not found"
    exit 1
fi 