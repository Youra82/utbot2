#!/bin/bash

# Bricht das Skript bei Fehlern sofort ab
set -e

echo "--- Sicheres Update für utbot2 wird ausgeführt ---"

# Schritt 1: Lokale Änderungen (deine secret.json) sicher beiseite legen
echo "1. Sichere deine lokalen Änderungen (insb. secret.json)..."
git stash

# Schritt 2: Neuesten Stand von GitHub holen
echo "2. Hole die neuesten Updates von GitHub..."
git pull origin main

# Schritt 3: Lokale Änderungen zurückholen und anwenden
echo "3. Stelle deine lokalen Änderungen wieder her..."
git stash pop

echo "✅ Update erfolgreich abgeschlossen. Dein Bot ist auf dem neuesten Stand."
