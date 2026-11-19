#!/usr/bin/env bash
# Gera dist/macaco_<versao>_all.deb. Uso: packaging/build-deb.sh
# O pacote leva só o código; o ambiente Python (PySide6, etc.) é criado no
# pós-instalação a partir de requirements.lock (precisa de internet).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep -m1 '^version' "$ROOT/pyproject.toml" | cut -d'"' -f2)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/macaco"

install -d "$PKG/DEBIAN" "$PKG/opt/macaco" "$PKG/usr/bin" \
  "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps"

cp -r "$ROOT/src" "$PKG/opt/macaco/src"
find "$PKG/opt/macaco" \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +
cp "$ROOT/requirements.lock" "$PKG/opt/macaco/"
cp "$ROOT/src/trinca/assets/macaco.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/trinca.svg"

cat > "$PKG/usr/bin/macaco" <<'LAUNCH'
#!/bin/sh
export PYTHONPATH=/opt/macaco/src
exec /opt/macaco/venv/bin/python -m trinca "$@"
LAUNCH

# O nome do arquivo precisa ser igual ao APP_ID (trinca) para o ícone casar com a janela.
cat > "$PKG/usr/share/applications/trinca.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Macaco
Comment=Estúdio de vídeos curtos de curiosidades
Exec=macaco
Icon=trinca
Terminal=false
Categories=AudioVideo;Video;
StartupWMClass=trinca
DESK

cat > "$PKG/DEBIAN/control" <<CTRL
Package: macaco
Version: $VERSION
Section: video
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-venv, libxcb-cursor0, libegl1, libgl1
Recommends: ffmpeg, google-chrome-stable | chromium
Maintainer: Macaco <noreply@localhost>
Description: Estúdio de vídeos curtos de curiosidades
 Transforma vídeos do YouTube em vídeos verticais para Shorts, Reels e TikTok.
 O ambiente Python é criado na instalação (requer internet).
CTRL

cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  python3 -m venv /opt/macaco/venv
  /opt/macaco/venv/bin/pip install --quiet --disable-pip-version-check -r /opt/macaco/requirements.lock
  command -v update-desktop-database >/dev/null && update-desktop-database -q || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
POST

cat > "$PKG/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
case "$1" in remove|purge) rm -rf /opt/macaco/venv ;; esac
PRE

chmod 755 "$PKG/usr/bin/macaco" "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"
mkdir -p "$ROOT/dist"
fakeroot dpkg-deb --build "$PKG" "$ROOT/dist/macaco_${VERSION}_all.deb"
echo "Gerado: dist/macaco_${VERSION}_all.deb"
