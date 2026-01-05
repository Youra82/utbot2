#!/bin/bash
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
VENV_PATH=".venv/bin/activate"
RESULTS_SCRIPT="src/utbot2/analysis/show_results.py"

source "$VENV_PATH"

# --- ERWEITERTES MODUS-MENÜ ---
echo -e "\n${YELLOW}Wähle einen Analyse-Modus für UtBot2:${NC}"
echo "  1) Einzel-Analyse (jede Strategie wird isoliert getestet)"
echo "  2) Manuelle Portfolio-Simulation (du wählst das Team)"
echo "  3) Automatische Portfolio-Optimierung (der Bot wählt das beste Team)"
echo "  4) Interaktive Charts (Ichimoku Cloud + Trade-Signale mit Entry/Exit Marker)"
read -p "Auswahl (1-4) [Standard: 1]: " MODE

# Validierung der Mode-Eingabe - Nur Ziffern 1-4 akzeptieren
if [[ ! "$MODE" =~ ^[1-4]?$ ]]; then
    echo -e "${RED}❌ Ungültige Eingabe! Verwende Standard (1).${NC}"
    MODE=1
fi

# Standard auf 1 setzen wenn leer
MODE=${MODE:-1}

# *** NEU: Max Drawdown Abfrage für Modus 3 ***
TARGET_MAX_DD=30 # Standardwert
if [ "$MODE" == "3" ]; then
    read -p "Gewünschter maximaler Drawdown in % für die Optimierung [Standard: 30]: " DD_INPUT
    # Prüfe, ob eine gültige Zahl eingegeben wurde, sonst nimm Standard
    if [[ "$DD_INPUT" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        TARGET_MAX_DD=$DD_INPUT
    else
        echo "Ungültige Eingabe, verwende Standard: ${TARGET_MAX_DD}%"
    fi
fi
# *** ENDE NEU ***

if [ ! -f "$RESULTS_SCRIPT" ]; then
    echo -e "${RED}Fehler: Die Analyse-Datei '$RESULTS_SCRIPT' wurde nicht gefunden.${NC}"
    deactivate
    exit 1
fi

# *** NEU: Übergebe Max DD an das Python Skript ***
python3 "$RESULTS_SCRIPT" --mode "$MODE" --target_max_drawdown "$TARGET_MAX_DD"

# --- OPTION 4: INTERAKTIVE CHARTS (Behandelt direkt in show_results.py) ---
if [ "$MODE" == "4" ]; then
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Interaktive Charts wurden generiert!${NC}"
    else
        echo -e "${RED}❌ Fehler beim Generieren der Charts.${NC}"
    fi
    
    deactivate
    exit 0
fi

deactivate