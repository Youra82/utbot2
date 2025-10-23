#!/bin/bash
echo "--- Starte utbot2 Tests ---"

# Aktiviere die virtuelle Umgebung
VENV_PATH=".venv/bin/activate"
if [ ! -f "$VENV_PATH" ]; then
    echo "Fehler: Virtuelle Umgebung nicht gefunden. Bitte 'install.sh' ausführen."
    exit 1
fi
source "$VENV_PATH"

# Führe pytest aus
# -v: Zeigt mehr Details pro Test
# -s: Zeigt print()-Ausgaben aus den Tests an
python3 -m pytest -v -s

# Deaktiviere die Umgebung
deactivate

echo "--- Tests abgeschlossen ---"
