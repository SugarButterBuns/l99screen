#!/usr/bin/env bash
# Build L99_Screen-<version>-x86_64.AppImage on Linux x86_64.
# Uses a relocatable Python (with Tk) from niess/python-appimage, installs l99screen into it,
# and packs it with appimagetool. Run from the repository root.
set -euo pipefail

PYVER="${PYVER:-3.12}"
ROOT="$(pwd)"
WORK="$ROOT/build/appimage"
DIST="$ROOT/dist"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
rm -rf "$WORK" && mkdir -p "$WORK" "$DIST"
cd "$WORK"

auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")

echo "== fetching Python $PYVER AppImage"
py_url="$(curl -fsSL "${auth[@]}" \
  "https://api.github.com/repos/niess/python-appimage/releases/tags/python$PYVER" |
  jq -r '.assets[].browser_download_url' |
  grep -E "manylinux2014_x86_64\.AppImage$" | sort -V | tail -1)"
echo "$py_url"
curl -fsSL -o python.AppImage "$py_url"
chmod +x python.AppImage
./python.AppImage --appimage-extract >/dev/null
mv squashfs-root AppDir

PY="$(ls -d AppDir/opt/python$PYVER/bin/python$PYVER)"
echo "== installing l99screen into $PY"
"$PY" -m pip install --no-cache-dir --no-warn-script-location "$ROOT[dnd]"

echo "== replacing launcher, desktop entry and icon"
rm -f AppDir/*.desktop AppDir/*.png AppDir/.DirIcon
rm -rf AppDir/usr/share/applications AppDir/usr/share/metainfo
install -Dm644 "$ROOT/packaging/appimage/l99screen.desktop" AppDir/l99screen.desktop
install -Dm644 "$ROOT/packaging/appimage/l99screen.desktop" AppDir/usr/share/applications/l99screen.desktop
install -Dm644 "$ROOT/packaging/appimage/l99screen.png" AppDir/l99screen.png
install -Dm644 "$ROOT/packaging/appimage/l99screen.png" AppDir/usr/share/icons/hicolor/256x256/apps/l99screen.png
ln -sf l99screen.png AppDir/.DirIcon
# The Python AppImage ships AppRun as a symlink into usr/bin: replace the link, don't write through it.
rm -f AppDir/AppRun
sed "s/@PYVER@/$PYVER/g" "$ROOT/packaging/appimage/AppRun" > AppDir/AppRun
chmod +x AppDir/AppRun

echo "== smoke tests"
AppDir/AppRun --help >/dev/null
AppDir/AppRun detect || true   # no keyboard on the build machine: expect "not found"
if command -v xvfb-run >/dev/null; then
  xvfb-run -a "$PY" -c "import tkinter, tkinterdnd2; r = tkinterdnd2.TkinterDnD.Tk(); r.destroy(); print('Tk + DnD OK')"
fi

echo "== packing"
curl -fsSL -o appimagetool \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool
OUT="$DIST/L99_Screen-$VERSION-x86_64.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 ./appimagetool --no-appstream AppDir "$OUT"
ls -l "$OUT"
