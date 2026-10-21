#!/bin/bash
# Builds "dist/Rocky Linux 9/Shelf-<version>-x86_64.AppImage".
# The AppImage holds only the shelf itself; it runs on the system's Python 3 and GTK 3.
# Needs appimagetool: tools/appimagetool-x86_64.AppImage, or set APPIMAGETOOL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${APPIMAGETOOL:-$ROOT/tools/appimagetool-x86_64.AppImage}"
APPDIR="$ROOT/build/Shelf.AppDir"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import shelf; print(shelf.__version__)' "$ROOT")"

if [ ! -x "$TOOL" ]; then
    echo "appimagetool not found at $TOOL (get it from github.com/AppImage/appimagetool/releases)" >&2
    exit 1
fi

rm -rf "$APPDIR"
OUTDIR="$ROOT/dist/Rocky Linux 9"
mkdir -p "$APPDIR/usr/share/shelf" "$OUTDIR"
cp -r "$ROOT/bin" "$ROOT/shelf" "$ROOT/data" "$APPDIR/usr/share/shelf/"
find "$APPDIR" -name __pycache__ -prune -exec rm -rf {} +
install -m 755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/app.shelf.Shelf.desktop" "$APPDIR/"
cp "$ROOT/data/icons/shelf.svg" "$APPDIR/app.shelf.Shelf.svg"
ln -s app.shelf.Shelf.svg "$APPDIR/.DirIcon"

OUT="$OUTDIR/Shelf-$VERSION-x86_64.AppImage"
# Build next to it and swap it in, so a copy that is running keeps working.
ARCH=x86_64 VERSION="$VERSION" "$TOOL" --no-appstream "$APPDIR" "$OUT.new"
mv -f "$OUT.new" "$OUT"
echo "Built $OUT"
