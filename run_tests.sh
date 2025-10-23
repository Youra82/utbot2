#!/bin/bash
# Dieses Skript führt das komplette Test-Sicherheitsnetz aus.
echo "--- Starte utbot2 Tests ---"

# Aktiviere die virtuelle Umgebung
VENV_PATH=".venv/bin/activate"
if [ ! -f "$VENV_PATH" ]; then
    echo "Fehler: Virtuelle Umgebung nicht gefunden. Bitte 'install.sh' ausführen."
    exit 1
fi
source "$VENV_PATH"

# Führe pytest aus. -v für mehr Details, -s um print() Ausgaben anzuzeigen.
python3 -m pytest -v -s tests/

# Deaktiviere die Umgebung wieder
deactivate

echo "--- Tests abgeschlossen ---"
