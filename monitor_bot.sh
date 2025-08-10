#!/bin/bash

# Pfad zur Log-Datei
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
# Pfad zur run.py, um Parameter auszulesen
RUN_PY_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"

# Stelle sicher, dass jq installiert ist
if ! command -v jq &> /dev/null
then
    echo "jq konnte nicht gefunden werden. Bitte installieren: sudo apt-get install jq"
    exit
fi

# --- Farbcodes für die Ausgabe ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}          ENVELOPE TRADING BOT MONITORING            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
echo -e "Letzte Aktualisierung: $(date)"
echo ""

# --- 1. Übersicht aller eingestellten Parameter ---
echo -e "${YELLOW}--- KONFIGURATIONSPARAMETER ---${NC}"
echo "'symbol': '$(grep "'symbol':" $RUN_PY_FILE | head -n 1 | cut -d"'" -f2)' - Das zu handelnde Währungspaar."
echo "'timeframe': '$(grep "'timeframe':" $RUN_PY_FILE | head -n 1 | cut -d"'" -f2)' - Die Zeiteinheit der Kerzen."
echo "'margin_mode': '$(grep "'margin_mode':" $RUN_PY_FILE | head -n 1 | cut -d"'" -f2)' - Margin-Modus (isolated/crossed)."
echo "'leverage': $(grep "'leverage':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Eingestellter Hebel."
echo "'use_longs': $(grep "'use_longs':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Long-Positionen erlaubt."
echo "'use_shorts': $(grep "'use_shorts':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Short-Positionen erlaubt."
echo ""

# --- 2. Übersicht der Strategieparameter ---
echo -e "${YELLOW}--- STRATEGIEPARAMETER (UT-BOT) ---${NC}"
echo "'ut_key_value': $(grep "'ut_key_value':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Sensitivität des ATR-Stops (höher = weniger empfindlich)."
echo "'ut_atr_period': $(grep "'ut_atr_period':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Periodenlänge für die ATR-Berechnung."
echo "'ut_heiken_ashi': $(grep "'ut_heiken_ashi':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Nutzung von Heikin-Ashi-Kerzen für Signale."
echo "'signal_lookback_period': $(grep "'signal_lookback_period':" $RUN_PY_FILE | head -n 1 | awk '{print $NF}' | tr -d ',' ) - Anzahl der Kerzen, die rückwirkend geprüft werden."
echo ""


# --- 3. Bot-Statistiken aus dem Log ---
echo -e "${YELLOW}--- BOT-STATISTIKEN (seit Log-Start) ---${NC}"
SIGNALS_GENERATED=$(grep -c "VALID_SIGNAL_DETECTED" "$LOG_FILE")
TRADES_OPENED=$(grep -c "POSITION_OPENED" "$LOG_FILE")

echo -e "Erzeugte Signale: ${GREEN}$SIGNALS_GENERATED${NC}"
echo -e "Ausgeführte Trades: ${GREEN}$TRADES_OPENED${NC}"
echo ""

# --- 4. Aktueller Status ---
echo -e "${YELLOW}--- AKTUELLER STATUS (letzter Durchlauf) ---${NC}"
LAST_BALANCE=$(grep "Verfügbarer Kontostand:" "$LOG_FILE" | tail -n 1 | awk -F': ' '{print $2}')
LAST_DECISION_JSON=$(grep "TRADE_DECISION:" "$LOG_FILE" | tail -n 1 | sed 's/.*TRADE_DECISION: //')

if [ -z "$LAST_BALANCE" ]; then
    echo -e "Kontostand: ${RED}Noch nicht im Log gefunden.${NC}"
else
    echo -e "Letzter Kontostand: ${GREEN}${LAST_BALANCE}${NC}"
fi

echo ""
echo -e "${YELLOW}--- LETZTE HANDLUNGSENTSCHEIDUNG ---${NC}"
if [ -z "$LAST_DECISION_JSON" ]; then
    echo -e "${RED}Keine Handelsentscheidung im Log gefunden.${NC}"
else
    # Nutze jq, um die JSON-Ausgabe schön zu formatieren
    echo "$LAST_DECISION_JSON" | jq .
fi

echo -e "${CYAN}=======================================================${NC}"
