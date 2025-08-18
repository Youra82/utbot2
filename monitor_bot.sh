#!/bin/bash

# Pfad zur Konfigurationsdatei
CONFIG_FILE="/home/ubuntu/utbot2/code/strategies/envelope/config.json"
# Pfad zur Log-Datei
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
# Pfad zum Python-Interpreter im venv
PYTHON_VENV="/home/ubuntu/utbot2/code/.venv/bin/python3"
# Pfad zum Backtest-Skript
BACKTEST_SCRIPT="/home/ubuntu/utbot2/code/analysis/backtest.py"

# --- Farbcodes für die Ausgabe ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

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
    
    # Führe das Python-Backtest-Skript aus
    $PYTHON_VENV $BACKTEST_SCRIPT --start $START_DATE --end $END_DATE --timeframe $TIMEFRAME

    exit 0
fi

# ==============================================================================
# MONITORING-MODUS (wird ausgeführt, wenn kein Argument übergeben wird)
# ==============================================================================
echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}          ENVELOPE TRADING BOT MONITORING            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
echo "Verwende './monitor_bot.sh backtest YYYY-MM-DD YYYY-MM-DD 1h' für einen Backtest."
echo -e "Letzte Aktualisierung: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# --- 1. Konfigurations- & Strategieparameter ---
echo -e "${YELLOW}--- KONFIGURATION & STRATEGIE ---${NC}"
if command -v jq &> /dev/null
then
    echo "Symbol: $(jq -r '.symbol' $CONFIG_FILE)"
    echo "Timeframe: $(jq -r '.timeframe' $CONFIG_FILE)"
    echo "Hebel: $(jq -r '.leverage' $CONFIG_FILE)x"
    echo "ATR Periode/Key: $(jq -r '.ut_atr_period' $CONFIG_FILE) / $(jq -r '.ut_key_value' $CONFIG_FILE)"
    echo "Stop-Loss ATR Multiplikator: $(jq -r '.stop_loss_atr_multiplier' $CONFIG_FILE)x"
    echo "Trade Size: $(jq -r '.trade_size_pct' $CONFIG_FILE)% des Kapitals"
else
    echo -e "${RED}Fehler: 'jq' ist nicht installiert. Bitte mit 'sudo apt-get install jq' installieren.${NC}"
fi
echo ""


# --- 2. Bot-Statistiken aus dem Log ---
echo -e "${YELLOW}--- BOT-STATISTIKEN (seit Log-Start) ---${NC}"
TRADES_OPENED=$(grep -c "eröffnet" "$LOG_FILE")
TRADES_CLOSED=$(grep -c "geschlossen" "$LOG_FILE")
echo -e "Eröffnete Trades: ${GREEN}$TRADES_OPENED${NC}"
echo -e "Geschlossene Trades: ${GREEN}$TRADES_CLOSED${NC}"
echo ""

# --- 3. Details zur aktuellen Position ---
echo -e "${YELLOW}--- AKTUELLE POSITION & RISIKO ---${NC}"
LAST_OPEN_LINE_NUM=$(grep -n "eröffnet" "$LOG_FILE" | tail -n 1 | cut -d: -f1)
LAST_CLOSE_LINE_NUM=$(grep -n "geschlossen" "$LOG_FILE" | tail -n 1 | cut -d: -f1)

if [ -n "$LAST_OPEN_LINE_NUM" ] && [ "$LAST_OPEN_LINE_NUM" -gt "${LAST_CLOSE_LINE_NUM:-0}" ]; then
    POSITION_INFO=$(grep "eröffnet" "$LOG_FILE" | tail -n 1)
    ENTRY_SIDE=$(echo "$POSITION_INFO" | awk '{print $4}')
    ENTRY_PRICE=$(echo "$POSITION_INFO" | awk '{print $6}')
    STOP_LOSS_PRICE=$(echo "$POSITION_INFO" | grep -o 'Stop-Loss bei [0-9.]*' | awk '{print $3}')

    echo -e "Status: ${GREEN}Position offen${NC}"
    echo -e "Seite: ${GREEN}${ENTRY_SIDE}${NC}"
    echo -e "Einstiegspreis: ${GREEN}${ENTRY_PRICE}${NC}"
    if [ -n "$STOP_LOSS_PRICE" ]; then
        echo -e "Stop-Loss: ${RED}${STOP_LOSS_PRICE}${NC}"
    else
        echo -e "Stop-Loss: ${YELLOW}Nicht im Log gefunden${NC}"
    fi
else
    echo -e "Status: ${CYAN}Keine Position offen${NC}"
fi
echo ""

# --- 4. System-Status ---
echo -e "${YELLOW}--- SYSTEM-STATUS ---${NC}"
LAST_LOG_TIMESTAMP_STR=$(tail -n 1 "$LOG_FILE" | cut -d ' ' -f 1,2)
if [ -n "$LAST_LOG_TIMESTAMP_STR" ]; then
    LAST_LOG_SECONDS=$(date -d "$LAST_LOG_TIMESTAMP_STR" +%s)
    CURRENT_SECONDS=$(date +%s)
    MINUTES_AGO=$(((CURRENT_SECONDS - LAST_LOG_SECONDS) / 60))
    echo -e "Letzte Aktivität: ${GREEN}vor $MINUTES_AGO Minuten${NC}"
else
    echo -e "Letzte Aktivität: ${RED}Keine Log-Datei gefunden${NC}"
fi

ERROR_COUNT=$(grep -c -i "Fehler\|error" "$LOG_FILE")
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo -e "Fehlerzähler: ${RED}${ERROR_COUNT} Fehler protokolliert${NC}"
else
    echo -e "Fehlerzähler: ${GREEN}Keine Fehler protokolliert${NC}"
fi

echo -e "${CYAN}=======================================================${NC}"
