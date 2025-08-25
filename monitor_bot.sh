#!/bin/bash

# Pfade zu wichtigen Dateien und Verzeichnissen
CONFIG_FILE="/home/ubuntu/utbot2/code/strategies/envelope/config.json"
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
PYTHON_VENV="/home/ubuntu/utbot2/code/.venv/bin/python3"
BACKTEST_SCRIPT="/home/ubuntu/utbot2/code/analysis/backtest.py"
OPTIMIZER_SCRIPT="/home/ubuntu/utbot2/code/analysis/optimizer.py"
CACHE_DIR="/home/ubuntu/utbot2/code/analysis/historical_data"

# --- Farbcodes für eine schönere Ausgabe ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Funktion für interaktive Analyse-Modi ---
function run_analysis() {
    local script_path=$1
    local mode_name=$2
    local script_args=""

    echo -e "${CYAN}=======================================================${NC}"
    echo -e "${CYAN}               ENVELOPE BOT - $mode_name MODUS               ${NC}"
    echo -e "${CYAN}=======================================================${NC}"

    read -p "Bitte geben Sie den Zeitraum ein (z.B. 2024-01-01 to 2024-06-30): " date_range_input
    START_DATE=$(echo $date_range_input | awk '{print $1}')
    END_DATE=$(echo $date_range_input | awk '{print $3}')
    script_args="--start $START_DATE --end $END_DATE"

    if [ "$mode_name" == "OPTIMIZER" ]; then
        read -p "Geben Sie die Timeframes getrennt durch Leerzeichen ein (z.B. 15m 1h 4h): " TIMEFRAMES
        script_args="$script_args --timeframes \"$TIMEFRAMES\""
        read -p "Handelspaar(e) eingeben (optional, z.B. BTC ETH): " SYMBOLS
        if [ -n "$SYMBOLS" ]; then
            script_args="$script_args --symbols $SYMBOLS"
        fi
        
        read -p "Risiko pro Trade in %% eingeben (optional, Enter zum Optimieren): " RISK_PERCENT
        if [ -n "$RISK_PERCENT" ]; then
            script_args="$script_args --risk $RISK_PERCENT"
        fi
    fi

    read -p "Startkapital in USDT eingeben (optional, Enter für 1000): " INITIAL_CAPITAL
    if [ -n "$INITIAL_CAPITAL" ]; then
        script_args="$script_args --initial_capital $INITIAL_CAPITAL"
    fi

    echo -e "${YELLOW}Starte $mode_name für $START_DATE bis $END_DATE...${NC}"
    eval "$PYTHON_VENV $script_path $script_args --top 10"
    exit 0
}

# --- MODUS-AUSWAHL ---
# Prüfe, ob ein Argument ($1) übergeben wurde
if [ -n "$1" ]; then
    case "$1" in
        backtest) 
            echo "Backtest-Modus ist veraltet. Bitte den Optimizer verwenden."
            exit 1
            ;;
        optimize) 
            run_analysis $OPTIMIZER_SCRIPT "OPTIMIZER" 
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
        *)
            echo "Unbekannter Modus: $1"
            echo "Verwende './monitor_bot.sh <mode>', Modi: ${GREEN}optimize, clear-cache${NC}"
            exit 1
            ;;
    esac
fi

# --- STANDARD-MONITORING-ANZEIGE ---
echo -e "${CYAN}=======================================================${NC}"
echo -e "${CYAN}           UT BOT v3.0 MONITORING (Cronjob-Modus)            ${NC}"
echo -e "${CYAN}=======================================================${NC}"
echo "Verwende './monitor_bot.sh <mode>', Modi: ${GREEN}optimize, clear-cache${NC}"
echo -e "Letzte Aktualisierung: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

echo -e "${YELLOW}--- KONFIGURATION & STRATEGIE ---${NC}"
if command -v jq &> /dev/null; then
    if [ -f "$CONFIG_FILE" ]; then
        SYMBOL=$(jq -r '.symbol' $CONFIG_FILE)
        TIMEFRAME=$(jq -r '.timeframe' $CONFIG_FILE)
        
        if [[ $(jq -r '.use_dynamic_leverage' $CONFIG_FILE) == "true" ]]; then
            MIN_LEV=$(jq -r '.min_leverage' $CONFIG_FILE)
            MAX_LEV=$(jq -r '.max_leverage' $CONFIG_FILE)
            echo "Symbol: $SYMBOL, Timeframe: $TIMEFRAME, Hebel: ${GREEN}Dynamisch (${MIN_LEV}x-${MAX_LEV}x)${NC}"
        else
            LEVERAGE=$(jq -r '.leverage' $CONFIG_FILE)
            echo "Symbol: $SYMBOL, Timeframe: $TIMEFRAME, Hebel: ${YELLOW}Fest (${LEVERAGE}x)${NC}"
        fi
        
        RISK=$(jq -r '.risk_per_trade_percent' $CONFIG_FILE)
        echo "Risiko pro Trade: ${RISK}%"

        ATR_PERIOD=$(jq -r '.ut_atr_period' $CONFIG_FILE)
        KEY_VALUE=$(jq -r '.ut_key_value' $CONFIG_FILE)
        echo "UT Bot: ATR Periode $ATR_PERIOD / Key Value $KEY_VALUE"
    else
        echo -e "${YELLOW}Warnung: config.json nicht gefunden.${NC}"
    fi
else
    echo -e "${RED}Fehler: 'jq' ist nicht installiert. Bitte mit 'sudo apt-get install jq' installieren.${NC}"
fi
echo ""

echo -e "${YELLOW}--- BOT-STATISTIKEN (seit Log-Start) ---${NC}"
if [ -f "$LOG_FILE" ]; then
    TRADES_OPENED=$(grep -c "Position eröffnet" "$LOG_FILE")
    TRADES_CLOSED=$(grep -c "Position geschlossen" "$LOG_FILE")
    echo "Eröffnete Trades: ${GREEN}$TRADES_OPENED${NC}, Geschlossene Trades: ${GREEN}$TRADES_CLOSED${NC}"
else
    echo "Log-Datei nicht gefunden."
fi
echo ""

echo -e "${YELLOW}--- AKTUELLE POSITION & RISIKO ---${NC}"
if [ -f "$LOG_FILE" ]; then
    LAST_OPEN_LINE=$(grep "Position eröffnet" "$LOG_FILE" | tail -n 1)
    LAST_CLOSE_LINE=$(grep "Position geschlossen" "$LOG_FILE" | tail -n 1)
    
    TS_OPEN=$(echo $LAST_OPEN_LINE | awk '{print $1" "$2}')
    TS_CLOSE=$(echo $LAST_CLOSE_LINE | awk '{print $1" "$2}')

    if [ -n "$LAST_OPEN_LINE" ] && [[ "$TS_OPEN" > "$TS_CLOSE" ]]; then
        POSITION_INFO=$(echo "$LAST_OPEN_LINE" | sed 's/.*INFO - //')
        echo -e "Status: ${GREEN}Position offen${NC}"
        echo -e "$POSITION_INFO"
    else
        echo -e "Status: ${CYAN}Keine Position offen${NC}"
    fi
else
    echo "Log-Datei nicht gefunden."
fi
echo ""

echo -e "${YELLOW}--- SYSTEM-STATUS ---${NC}"
if [ -f "$LOG_FILE" ]; then
    if [ -s "$LOG_FILE" ]; then
        LAST_LOG_SECONDS=$(date -d "$(tail -n 1 "$LOG_FILE" | cut -d ' ' -f 1,2)" +%s)
        MINUTES_AGO=$((( $(date +%s) - LAST_LOG_SECONDS) / 60))
        echo "Letzte Aktivität: ${GREEN}vor $MINUTES_AGO Minuten${NC}"
    else
        echo "Letzte Aktivität: ${YELLOW}Log-Datei ist leer.${NC}"
    fi
    
    ERROR_COUNT=$(grep -c -iE "Fehler|error" "$LOG_FILE")
    [ "$ERROR_COUNT" -gt 0 ] && echo -e "Fehlerzähler: ${RED}${ERROR_COUNT} Fehler protokolliert${NC}" || echo -e "Fehlerzähler: ${GREEN}Keine Fehler${NC}"
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "" 
        echo -e "${YELLOW}--- LETZTE FEHLERMELDUNGEN ---${NC}"
        grep -iE "Fehler|error" "$LOG_FILE" | tail -n 5 | while IFS= read -r line; do
            echo -e "${RED}- $line${NC}"
        done
    fi
else
    echo -e "${RED}Keine Log-Datei gefunden unter $LOG_FILE${NC}"
fi

echo -e "${CYAN}=======================================================${NC}"
