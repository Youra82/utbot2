#!/bin/bash

# Pfad zur Konfigurationsdatei
CONFIG_FILE="/home/ubuntu/utbot2/code/strategies/envelope/config.json"
# Pfad zur Log-Datei
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
# Pfad zum Python-Interpreter im venv
PYTHON_VENV="/home/ubuntu/utbot2/code/.venv/bin/python3"
# Pfad zum Backtest-Skript
BACKTEST_SCRIPT="/home/ubuntu/utbot2/code/analysis/backtest.py"
# NEU: Pfad zum Cache-Verzeichnis
CACHE_DIR="/home/ubuntu/utbot2/code/analysis/historical_data"

# --- Farbcodes für die Ausgabe ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ==============================================================================
# NEU: CACHE LÖSCHEN MODUS
# ==============================================================================
if [ "$1" == "clear-cache" ]; then
    echo -e "${YELLOW}Möchtest du den gesamten Daten-Cache im Verzeichnis löschen?${NC}"
    echo -e "Verzeichnis: ${CYAN}$CACHE_DIR${NC}"
    read -p "Bestätige mit [j/N]: " response
    if [[ "$response" =~ ^([jJ][aA]|[jJ])$ ]]; then
        if [ -d "$CACHE_DIR" ]; then
            rm -r "$CACHE_DIR"
            echo -e "${GREEN}✔ Cache wurde erfolgreich gelöscht.${NC}"
        else
            echo -e "${YELLOW}i Cache-Verzeichnis existiert nicht, nichts zu tun.${NC}"
        fi
    else
        echo -e "${RED}Aktion abgebrochen.${NC}"
    fi
    exit 0
fi

# ==============================================================================
# BACKTEST-MODUS
# ==============================================================================
if [ "$1" == "backtest" ]; then
    if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
        echo -e "${RED}Fehler: Für den Backtest werden Startdatum, Enddatum und Timeframe benötigt.${NC}"
        echo "Beispiel: ./monitor_bot.sh backtest 2024-01-01 2024-06-30 4h"
        exit 1
    fi
    
    START_DATE=$2
    END_DATE=$3
    TIMEFRAME=$4

    echo -e "${CYAN}=======================================================${NC}"
    echo -e "${CYAN}             ENVELOPE BOT - BACKTEST MODUS             ${NC}"
    echo -e "${CYAN}=======================================================${NC}"
    
    $PYTHON_VENV $BACKTEST_SCRIPT --start $START_DATE --end $END_DATE --timeframe $TIMEFRAME
    exit 0
fi

# ==============================================================================
# MONITORING-MODUS
# ==============================================================================
echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}          ENVELOPE TRADING BOT MONITORING            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
echo "Verwende './monitor_bot.sh backtest ...' für einen Backtest."
echo "Verwende './monitor_bot.sh clear-cache' um den Daten-Cache zu löschen."
echo -e "Letzte Aktualisierung: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# --- (Rest des Skripts bleibt unverändert) ---

echo -e "${YELLOW}--- KONFIGURATION & STRATEGIE ---${NC}"
if command -v jq &> /dev/null
then
    echo "Symbol: $(jq -r '.symbol' $CONFIG_FILE)"
    echo "Timeframe: $(jq -r '.timeframe' $CONFIG_FILE)"
    # ... (weitere jq-Befehle wie zuvor)
else
    echo -e "${RED}Fehler: 'jq' ist nicht installiert.${NC}"
fi
echo ""
# ... (Rest des Monitoring-Teils)
