#!/bin/bash
set -e # Exit immediately if a command exits with a non-zero status.

TARGETDIR=$1
if [ "$TARGETDIR" = "" ]; then
  # Ensure TARGETDIR is an absolute path
  TARGETDIR="$(cd "$(dirname "$0")" && pwd)/local"
fi
echo "Building static tmux and dependencies in: $TARGETDIR"
mkdir -p "$TARGETDIR"

# Clean up previous build attempts to ensure a fresh state
echo "Cleaning up previous build directories..."
rm -rf libevent-2.1.12-stable ncurses-6.5 tmux-3.5a

libevent() {
  echo "Building libevent..."
  curl -LO https://github.com/libevent/libevent/releases/download/release-2.1.12-stable/libevent-2.1.12-stable.tar.gz
  tar -zxvf libevent-2.1.12-stable.tar.gz
  cd libevent-2.1.12-stable
  ./configure --prefix="$TARGETDIR" --enable-static --disable-shared --disable-openssl && make V=1 && make install
  cd ..
  echo "libevent build completed."
  echo "Checking for libevent.pc..."
  if [ ! -f "$TARGETDIR/lib/pkgconfig/libevent.pc" ]; then
    echo "ERROR: libevent.pc not found after libevent build!"
    ls -l "$TARGETDIR/lib/pkgconfig/"
    exit 1
  fi
  echo "libevent.pc found."
}

ncurses() {
  echo "Building ncurses..."
  curl -LO https://ftp.gnu.org/pub/gnu/ncurses/ncurses-6.5.tar.gz
  tar zxvf ncurses-6.5.tar.gz
  cd ncurses-6.5
  # For ncurses, static build often requires --with-shared --without-debug --without-ada --enable-widec
  # and CFLAGS for position-independent code if not default.
  # However, let's first try with simpler static flags. The --with-pkg-config-libdir is key.
  ./configure --prefix="$TARGETDIR" \
              --enable-static --disable-shared \
              --with-default-terminfo-dir="$TARGETDIR/share/terminfo" \
              --with-terminfo-dirs="$TARGETDIR/share/terminfo" \
              --enable-pc-files \
              --with-pkg-config-libdir="$TARGETDIR/lib/pkgconfig" \
  && make V=1 && make install
  cd ..
  echo "ncurses build completed."
}

tmux() {
  echo "Building tmux..."
  curl -LO https://github.com/tmux/tmux/releases/download/3.5a/tmux-3.5a.tar.gz
  tar zxvf tmux-3.5a.tar.gz
  cd tmux-3.5a
  
  # Set environment variables to help configure find our static libs
  export PKG_CONFIG_PATH="$TARGETDIR/lib/pkgconfig"
  export CPPFLAGS="-I$TARGETDIR/include -I$TARGETDIR/include/ncurses"
  export LDFLAGS="-L$TARGETDIR/lib"
  
  # Check if libevent.pc can be found by pkg-config with the current PKG_CONFIG_PATH
  echo "Verifying libevent via pkg-config..."
  pkg-config --exists --print-errors libevent || (echo "pkg-config cannot find libevent. Check PKG_CONFIG_PATH." && exit 1)
  echo "libevent found by pkg-config."
  
  # The static flags might need to be passed to LDFLAGS as well for some systems
  # Forcing static linking by explicitly adding .a files might be needed if this fails
  ./configure --enable-static --prefix="$TARGETDIR" && make V=1 && make install
  cd ..
  echo "tmux build completed."
  echo "Static tmux binary is now at $TARGETDIR/bin/tmux"
}

libevent
ncurses
tmux

echo "All builds finished." 