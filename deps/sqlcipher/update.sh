#!/bin/zsh
# Regenerates sqlite3.c and sqlite3.h from a SQLCipher release (BSD licence, see LICENSE.md).
# Usage: deps/sqlcipher/update.sh v4.12.0
set -e
tag=${1:?usage: update.sh <sqlcipher tag, e.g. v4.12.0>}
here=${0:A:h}
work=$(mktemp -d)
git clone --depth 1 --branch $tag https://github.com/sqlcipher/sqlcipher.git $work/sqlcipher
cd $work/sqlcipher
./configure --with-tempstore=yes --disable-tcl \
  CFLAGS="-DSQLITE_HAS_CODEC -DSQLITE_EXTRA_INIT=sqlcipher_extra_init -DSQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown -DSQLCIPHER_CRYPTO_CC" \
  LDFLAGS="-framework Security -framework CoreFoundation"
make sqlite3.c
cp sqlite3.c sqlite3.h LICENSE.md $here/
echo "$tag" > $here/SQLCIPHER_VERSION.txt
rm -rf $work
