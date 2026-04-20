#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/wallpaper_picker.py"
DESKTOP_DIR="$HOME/.config/autostart"
DESKTOP_FILE="$DESKTOP_DIR/wallpaper-picker.desktop"

echo "=== Wallpaper Picker Installer ==="

# Check PyQt6
if ! python -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
    echo "ERROR: PyQt6 nicht gefunden. Installieren mit: sudo pacman -S python-pyqt6"
    exit 1
fi
echo "[OK] PyQt6 gefunden"

# Check plasma-apply-wallpaperimage
if ! command -v plasma-apply-wallpaperimage &>/dev/null; then
    echo "ERROR: plasma-apply-wallpaperimage nicht gefunden. Installieren mit: sudo pacman -S plasma-workspace"
    exit 1
fi
echo "[OK] plasma-apply-wallpaperimage gefunden"

# Check wallpaper directory
if [ ! -d "/home/xz0/wallpapers" ]; then
    echo "WARNUNG: /home/xz0/wallpapers existiert nicht. Ordner anlegen und Bilder reinkopieren."
fi

# Create autostart entry
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Wallpaper Picker
Exec=python "$SCRIPT"
Type=Application
X-KDE-AutostartEnabled=true
EOF
echo "[OK] Autostart-Eintrag erstellt: $DESKTOP_FILE"

echo ""
echo "=== Manueller Schritt: Tastenkürzel eintragen ==="
echo "1. Systemeinstellungen → Tastenkürzel → Eigene Tastenkürzel"
echo "2. Bearbeiten → Neu → Globales Tastenkürzel → Befehl/URL"
echo "3. Name: Wallpaper Picker"
echo "4. Auslöser: Shift+Alt+W"
echo "5. Aktion: python \"$SCRIPT\""
echo ""
echo "Installation abgeschlossen. Jetzt starten mit:"
echo "  python \"$SCRIPT\" &"
