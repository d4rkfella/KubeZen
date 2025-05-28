#!/bin/bash

docker run -i --rm -v "$PWD":/out -w /root alpine /bin/sh <<EOF
apk add gcc make musl-dev ncurses-static git
wget https://github.com/vim/vim/archive/refs/tags/v9.1.1415.tar.gz -O vim-v9.1.1415.tar.gz
tar xvfz vim-v9.1.1415.tar.gz
cd vim-9.1.1415
LDFLAGS="-static" ./configure --disable-channel --disable-gpm --disable-gtktest --disable-gui --disable-netbeans --disable-nls --disable-selinux --disable-smack --disable-sysmouse --disable-xsmp --enable-multibyte --with-features=huge --without-x --with-tlib=ncursesw
make
make install
mkdir -p /out/vim_static_build
cp -r /usr/local/* /out/vim_static_build
strip /out/vim_static_build/bin/vim
chown -R $(id -u):$(id -g) /out/vim_static_build
echo "Static vim build complete. Files in ./vim_static_build"
EOF 