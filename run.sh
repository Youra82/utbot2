#!/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
VENV_PATH="$SCRIPT_DIR/.venv/bin/activate"
MAIN_SCRIPT="$SCRIPT_DIR/main.py"

if [ ! -f "$VENV_PATH" ]; then
    echo "Fehler: Virtuelle Umgebung nicht gefunden. Bitte 'install.sh' ausführen."
    exit 1
fi

source "$VENV_PATH"
python3 "$MAIN_SCRIPT"
deactivate
