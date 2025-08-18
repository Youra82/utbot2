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
function run_interactive_analysis() {
    local script_path=$1
    local mode_name=$2
    
    echo -e "${CYAN}=======================================================${NC}"
    echo -e "${CYAN}             ENVELOPE BOT - $mode_name MODUS             ${NC}"
    echo -e "${CYAN}=======================================================${NC}"

    read -p "Bitte geben Sie den Zeitraum ein (z.B. 2023-01-01 to 2023-12-31): " date_range_input
    START_DATE=$(echo $date_range_input | awk '{print $1}')
    END_DATE=$(echo $date_range_input | awk '{print $3}')

    read -p "Bitte geben Sie den Timeframe ein (z.B. 15m, 1h, 4h): " TIMEFRAME

    if [ -z "$START_DATE" ] || [ -z "$END_DATE" ] || [ -z "$TIMEFRAME" ]; then
        echo -e "${RED}Fehler: Ungültige Eingabe.${NC}"
        exit 1
    fi

    echo -e "${YELLOW}Starte $mode_name für $START_DATE bis $END_DATE mit Timeframe $TIMEFRAME...${NC}"
    $PYTHON_VENV $script_path --start $START_DATE --end $END_DATE --timeframe $TIMEFRAME
    exit 0
}

# --- MODUS-AUSWAHL ---
case "$1" in
    backtest)
        run_interactive_analysis $BACKTEST_SCRIPT "BACKTEST"
        ;;
    optimize)
        run_interactive_analysis $OPTIMIZER_SCRIPT "OPTIMIZER"
        ;;
    clear-cache)
        echo -e "${YELLOW}Möchtest du den gesamten Daten-Cache löschen? (${CYAN}$CACHE_DIR${YELLOW})${NC}"
        read -p "Bestätige mit [j/N]: " response
        if [[ "$response" =~ ^([jJ][aA]|[jJ])$ ]]; then
            rm -rf "$CACHE_DIR" && echo -e "${GREEN}✔ Cache wurde erfolgreich gelöscht.${NC}"
        else
            echo -e "${RED}Aktion abgebrochen.${NC}"
        fi
        exit 0
        ;;
esac

# --- MONITORING-MODUS (Standard) ---
echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}          ENVELOPE TRADING BOT MONITORING            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
echo "Verwende './monitor_bot.sh <mode>', Modi: ${GREEN}backtest, optimize, clear-cache${NC}"
echo -e "Letzte Aktualisierung: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# --- KONFIGURATION ANZEIGEN ---
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Fehler: 'jq' ist nicht installiert. Bitte mit 'sudo apt-get install jq' installieren.${NC}"
    exit 1
fi

echo -e "${YELLOW}--- KONFIGURATION & STRATEGIE ---${NC}"
echo "Symbol: $(jq -r '.symbol' $CONFIG_FILE), Timeframe: $(jq -r '.timeframe' $CONFIG_FILE), Hebel: $(jq -r '.leverage' $CONFIG_FILE)x"
echo "Trade Size: $(jq -r '.trade_size_pct' $CONFIG_FILE)% des Kapitals"
echo "UT Bot: ATR Periode $(jq -r '.ut_atr_period' $CONFIG_FILE) / Key Value $(jq -r '.ut_key_value' $CONFIG_FILE)"
echo "Stop-Loss: ATR Multiplikator $(jq -r '.stop_loss_atr_multiplier' $CONFIG_FILE), Trailing: $(jq -r '.enable_trailing_stop_loss' $CONFIG_FILE)"
if [[ $(jq -r '.use_adx_filter' $CONFIG_FILE) == "true" ]]; then
    echo -e "ADX Filter: ${GREEN}Aktiv${NC} (Window: $(jq -r '.adx_window' $CONFIG_FILE), Threshold: $(jq -r '.adx_threshold' $CONFIG_FILE))"
else
    echo -e "ADX Filter: ${RED}Inaktiv${NC}"
fi
echo ""

# --- BOT-STATISTIKEN aus dem Log ---
echo -e "${YELLOW}--- BOT-STATISTIKEN (seit Log-Start) ---${NC}"
if [ -f "$LOG_FILE" ]; then
    TRADES_OPENED=$(grep -c "eröffnet" "$LOG_FILE")
    TRADES_CLOSED=$(grep -c "geschlossen" "$LOG_FILE")
    echo "Eröffnete Trades: ${GREEN}$TRADES_OPENED${NC}, Geschlossene Trades: ${GREEN}$TRADES_CLOSED${NC}"
else
    echo "Log-Datei nicht gefunden."
fi
echo ""

# --- AKTUELLE POSITION & RISIKO ---
echo -e "${YELLOW}--- AKTUELLE POSITION & RISIKO ---${NC}"
if [ -f "$LOG_FILE" ]; then
    LAST_OPEN_LINE=$(grep "Position bei" "$LOG_FILE" | tail -n 1)
    LAST_CLOSE_LINE=$(grep "Position geschlossen" "$LOG_FILE" | tail -n 1)

    if [ -n "$LAST_OPEN_LINE" ] && [ "$(echo -e "$LAST_OPEN_LINE\n$LAST_CLOSE_LINE" | sort | tail -n 1)" == "$LAST_OPEN_LINE" ]; then
        POSITION_INFO=$(echo "$LAST_OPEN_LINE" | sed 's/.*UTC: //')
        ENTRY_SIDE=$(echo "$POSITION_INFO" | awk '{print $1}')
        ENTRY_PRICE=$(echo "$POSITION_INFO" | grep -oP '@ \K[0-9.]+')
        STOP_LOSS_PRICE=$(echo "$POSITION_INFO" | grep -oP 'Stop-Loss bei \K[0-9.]+')
        
        echo -e "Status: ${GREEN}Position offen${NC}"
        echo -e "Seite: ${GREEN}${ENTRY_SIDE}${NC}, Einstieg: ${GREEN}${ENTRY_PRICE}${NC}, SL: ${RED}${STOP_LOSS_PRICE:-N/A}${NC}"
    else
        echo -e "Status: ${CYAN}Keine Position offen${NC}"
    fi
else
    echo "Log-Datei nicht gefunden."
fi
echo ""

# --- SYSTEM-STATUS ---
echo -e "${YELLOW}--- SYSTEM-STATUS ---${NC}"
if [ -f "$LOG_FILE" ]; then
    LAST_LOG_SECONDS=$(date -d "$(tail -n 1 "$LOG_FILE" | cut -d ' ' -f 1,2)" +%s)
    MINUTES_AGO=$((( $(date +%s) - LAST_LOG_SECONDS) / 60))
    echo "Letzte Aktivität: ${GREEN}vor $MINUTES_AGO Minuten${NC}"
    
    ERROR_COUNT=$(grep -c -iE "Fehler|error" "$LOG_FILE")
    [ "$ERROR_COUNT" -gt 0 ] && echo -e "Fehlerzähler: ${RED}${ERROR_COUNT} Fehler protokolliert${NC}" || echo -e "Fehlerzähler: ${GREEN}Keine Fehler${NC}"
else
    echo -e "${RED}Keine Log-Datei gefunden unter $LOG_FILE${NC}"
fi

echo -e "${CYAN}=======================================================${NC}"
