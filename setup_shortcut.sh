#!/bin/bash
# Creates a desktop shortcut for Pitwall IQ (Linux/macOS).
# Run once after downloading: bash setup_shortcut.sh

DIR="$(cd "$(dirname "$0")" && pwd)"

# Make launchers executable
chmod +x "$DIR/launch_mac.command" 2>/dev/null
chmod +x "$DIR/launch_linux.sh"    2>/dev/null

# Linux: install .desktop file
if [[ "$OSTYPE" == "linux"* ]]; then
    DESKTOP_FILE="$HOME/.local/share/applications/PitwallIQ.desktop"
    sed "s|INSTALL_PATH|$DIR|g" "$DIR/PitwallIQ.desktop" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"
    echo "Desktop shortcut created at: $DESKTOP_FILE"
    echo "You can also find Pitwall IQ in your application launcher."
fi

# macOS: just remind the user the .command file is ready
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Setup complete!"
    echo "Double-click launch_mac.command in Finder to start Pitwall IQ."
    echo "(If macOS blocks it, right-click → Open the first time.)"
fi

echo ""
echo "Done. Run python3 F1_lap_tracker.py or use the launcher to start."
