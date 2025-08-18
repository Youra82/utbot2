#!/bin/bash

# Pfad zur Konfigurationsdatei
CONFIG_FILE="/home/ubuntu/utbot2/code/strategies/envelope/config.json"
# Pfad zur Log-Datei
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
# Pfad zum Python-Interpreter im venv
PYTHON_VENV="/home/ubuntu/utbot2/code/.venv/bin/python3"
# Pfade zu den Analyse-Skripten
BACKTEST_SCRIPT="/home/ubuntu/utbot2/code/analysis/backtest.py"
OPTIMIZER_SCRIPT="/home/ubuntu/utbot2/code/analysis/optimizer.py"
# Pfad zum Cache-Verzeichnis
CACHE_DIR="/home/ubuntu/utbot2/code/analysis/historical_data"

# --- Farbcodes ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# --- FUNKTIONEN ---
function run_analysis() {
    local script_path=$1
    local mode_name=$2
    local script_args=""

    echo -e "${CYAN}=======================================================${NC}"
    echo -e "${CYAN}             ENVELOPE BOT - $mode_name MODUS             ${NC}"
    echo -e "${CYAN}=======================================================${NC}"

    read -p "Bitte geben Sie den Zeitraum ein (z.B. 2024-01-01 to 2024-06-30): " date_range_input
    START_DATE=$(echo $date_range_input | awk '{print $1}')
    END_DATE=$(echo $date_range_input | awk '{print $3}')

    if [ -z "$START_DATE" ] || [ -z "$END_DATE" ]; then
        echo -e "${RED}Fehler: Ungültiges Datum.${NC}"
        exit 1
    fi
    script_args="--start $START_DATE --end $END_DATE"

    if [ "$mode_name" == "BACKTEST" ]; then
        read -p "Bitte geben Sie den Timeframe ein (z.B. 1h): " TIMEFRAME
        script_args="$script_args --timeframe $TIMEFRAME"
    elif [ "$mode_name" == "OPTIMIZER" ]; then
        # NEU: Frage nach mehreren Timeframes
        read -p "Geben Sie die Timeframes getrennt durch Leerzeichen ein (z.B. 15m 1h 4h): " TIMEFRAMES
        script_args="$script_args --timeframes \"$TIMEFRAMES\""
    fi

    echo -e "${YELLOW}Starte $mode_name für $START_DATE bis $END_DATE...${NC}"
    eval "$PYTHON_VENV $script_path $script_args"
    exit 0
}


# --- MODUS-AUSWAHL ---
case "$1" in
    backtest)
        run_analysis $BACKTEST_SCRIPT "BACKTEST"
        ;;
    optimize)
        run_analysis $OPTIMIZER_SCRIPT "OPTIMIZER"
        ;;
    clear-cache)
        echo -e "${YELLOW}Mötest du den gesamten Daten-Cache löschen? (${CYAN}$CACHE_DIR${YELLOW})${NC}"
        read -p "Bestätige mit [j/N]: " response
        if [[ "$response" =~ ^([jJ][aA]|[jJ])$ ]]; then
            rm -rf "$CACHE_DIR" && echo -e "${GREEN}✔ Cache wurde erfolgreich gelöscht.${NC}"
        else
            echo -e "${RED}Aktion abgebrochen.${NC}"
        fi
        exit 0
        ;;
esac

# ... der Rest des Monitor-Skripts bleibt unverändert ...
echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}          ENVELOPE TRADING BOT MONITORING            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
# ...

