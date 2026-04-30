#!/usr/bin/env bash
# Build TomoTexture as a Linux AppImage (Steam Deck friendly).
#
# Must run on Linux. Requires:
#   - python3 (3.10+) with venv + pip
#   - python3-tk (system Tk libraries)
#   - wget, file, fuse (libfuse2)
#
# Usage: ./build-linux.sh
# Output: dist/TomoTexture-x86_64.AppImage

set -euo pipefail

APP_NAME="TomoTexture"
ENTRY="app.py"
ICON_PNG="safezone.png"
PY="${PYTHON:-python3}"
VENV_DIR="venv-linux"
BUILD_DIR="build-linux"
DIST_DIR="dist"
APPDIR="${BUILD_DIR}/${APP_NAME}.AppDir"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "error: build-linux.sh must run on Linux." >&2
  exit 1
fi

echo "==> Building ${APP_NAME} AppImage"

mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "==> Creating Linux build venv"
  "${PY}" -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Installing dependencies"
python -m pip install --upgrade pip wheel >/dev/null
python -m pip install -r requirements.txt pyinstaller >/dev/null

echo "==> Running PyInstaller"
pyinstaller \
  --noconfirm \
  --clean \
  --name "${APP_NAME}" \
  --add-data "${ICON_PNG}:." \
  --hidden-import "PIL._tkinter_finder" \
  --windowed \
  "${ENTRY}"

PYI_OUT="${DIST_DIR}/${APP_NAME}"
if [[ ! -d "${PYI_OUT}" ]]; then
  echo "error: PyInstaller did not produce ${PYI_OUT}" >&2
  exit 1
fi

echo "==> Building AppDir at ${APPDIR}"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/share/applications" "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

cp -R "${PYI_OUT}/." "${APPDIR}/usr/bin/"
cp "${ICON_PNG}" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"
cp "${ICON_PNG}" "${APPDIR}/${APP_NAME}.png"
cp "${ICON_PNG}" "${APPDIR}/.DirIcon"

cat > "${APPDIR}/usr/share/applications/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Save canvas editor for Tomodachi Life
Exec=${APP_NAME}
Icon=${APP_NAME}
Categories=Utility;Game;
Terminal=false
EOF
cp "${APPDIR}/usr/share/applications/${APP_NAME}.desktop" "${APPDIR}/${APP_NAME}.desktop"

cat > "${APPDIR}/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH:-}"
exec "${HERE}/usr/bin/TomoTexture" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

APPIMAGETOOL="${BUILD_DIR}/appimagetool-x86_64.AppImage"
if [[ ! -x "${APPIMAGETOOL}" ]]; then
  echo "==> Downloading appimagetool"
  wget -q -O "${APPIMAGETOOL}" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "${APPIMAGETOOL}"
fi

ARCH="${ARCH:-x86_64}"
APPIMAGE_PATH="${DIST_DIR}/${APP_NAME}-${ARCH}.AppImage"
echo "==> Producing ${APPIMAGE_PATH}"
ARCH="${ARCH}" "${APPIMAGETOOL}" --no-appstream "${APPDIR}" "${APPIMAGE_PATH}"

echo
echo "==> Done"
echo "    AppImage: ${APPIMAGE_PATH}"
echo
echo "Run on Steam Deck (Desktop Mode) or any Linux desktop:"
echo "    chmod +x ${APP_NAME}-${ARCH}.AppImage"
echo "    ./${APP_NAME}-${ARCH}.AppImage"
