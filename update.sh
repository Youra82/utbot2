#!/bin/bash
set -e

echo "--- Sicheres Update wird ausgeführt (Robuste Version) ---"

# 1. Sichere die einzige Datei, die lokal wichtig ist
echo "1. Erstelle ein Backup von 'secret.json'..."
if [ -f "secret.json" ]; then
    cp secret.json secret.json.bak
else
    echo "Warnung: 'secret.json' nicht gefunden, erstelle leeres Backup."
    touch secret.json.bak
fi

# 2. Hole die neuesten Daten von GitHub
echo "2. Hole den neuesten Stand von GitHub..."
git fetch origin

# 3. Setze das lokale Verzeichnis hart auf den Stand von GitHub zurück
echo "3. Setze alle Dateien auf den neuesten Stand zurück und verwerfe lokale Änderungen..."
git reset --hard origin/main

# 4. Stelle die API-Schlüssel aus dem Backup wieder her
echo "4. Stelle den Inhalt von 'secret.json' aus dem Backup wieder her..."
cp secret.json.bak secret.json
rm secret.json.bak

echo "✅ Update erfolgreich abgeschlossen. Dein Bot ist jetzt auf dem neuesten Stand."
