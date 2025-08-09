#!/bin/bash
# monitor_bot.sh - Erweiterte Überwachung des Trading-Bots

# Konfiguration
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
TRACKER_FILE="/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"
RUN_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"
SECRET_FILE="/home/ubuntu/utbot2/secret.json"
KEY_NAME="envelope"

# Funktionen
print_header() {
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

# 1. Parameterübersicht mit Erklärungen
print_header "STRATEGIEPARAMETER"
params_section=$(awk '/params = \{/,/^}/' "$RUN_FILE")
echo "$params_section" | awk -F '#' '/^ *'\''/ {
    param = $1;
    gsub(/^ *'\''|,/, "", param);
    gsub(/:.*/, "", param);
    getline;
    desc = $0;
    gsub(/^ *# */, "", desc);
    printf "%-25s: %s\n", param, desc;
}'

# 2. Handelsstatistiken
print_header "HANDELSSTATISTIK"
signals_line=$(grep "Gefundene Signale" "$LOG_FILE" | tail -1)
trades_count=$(grep "POSITION_OPENED" "$LOG_FILE" | grep "TRADE_DECISION" | wc -l)
balance_line=$(grep "Verfügbarer Kontostand" "$LOG_FILE" | tail -1)

# Verbesserte Extraktion
signals_count=$(echo "$signals_line" | grep -oP '\d+ Signale' | awk '{print $1}')
balance=$(echo "$balance_line" | grep -oP '\d+\.\d{2}' | head -1)

echo "Signale (letzte Ausführung) : ${signals_count:-0}"
echo "Eröffnete Trades (gesamt)   : ${trades_count:-0}"
echo "Aktueller Kontostand        : ${balance:-0} USDT"

# 3. Detaillierte Handelsentscheidungen
print_header "DETAILLIERTE HANDELSENTSCHEDUNGEN"
{
    echo "Zeit | Symbol | Signal | Entscheidung | Details"
    echo "------------------------------------------------------------"
    grep "TRADE_DECISION" "$LOG_FILE" | tail -10 | while read -r line; do
        json_data=$(echo "$line" | sed 's/.*TRADE_DECISION: //')
        timestamp=$(echo "$json_data" | jq -r '.timestamp')
        symbol=$(echo "$json_data" | jq -r '.symbol')
        signal=$(echo "$json_data" | jq -r '.signal')
        decision=$(echo "$json_data" | jq -r '.decision')
        details=$(echo "$json_data" | jq -r '.details | tostring' | sed 's/^{//;s/}$//;s/"//g')
        printf "%s | %s | %s | %s | %s\n" "$timestamp" "$symbol" "$signal" "$decision" "$details"
    done
} | column -t -s "|"

# 4. Signalanalyse
print_header "SIGNALANALYSE"
{
    echo "Zeit | Signal | Aktion | Grund"
    echo "-----------------------------------------------"
    grep -E "Gefundene Signale|Verwende|Signal abgelaufen|Öffne|Schließe|Status ist" "$LOG_FILE" \
    | tac \
    | awk '
        /Gefundene Signale/ {signals=$5; next}
        /Verwende Kauf-Signal/ {
            signal = "Kauf"
            reason = ""
            for(i=4; i<=NF; i++) reason = reason $i " "
            printf "%s | %s | ✅ REAGIERT | %s\n", $1, signal, reason
        }
        /Verwende Verkauf-Signal/ {
            signal = "Verkauf"
            reason = ""
            for(i=4; i<=NF; i++) reason = reason $i " "
            printf "%s | %s | ✅ REAGIERT | %s\n", $1, signal, reason
        }
        /Signal abgelaufen/ {
            signal = ($4 == "Kauf-Signal") ? "Kauf" : "Verkauf"
            printf "%s | %s | ❌ IGNORIERT | Preisänderung zu groß\n", $1, signal
        }
        /Status ist/ {
            status = $4
            sub(/,/, "", status)
            printf "%s | - | ❌ IGNORIERT | Tracker-Status: %s\n", $1, status
        }
        /Öffne Long-Position/ {
            signal = "Kauf"
            reason = $0
            printf "%s | %s | 🟢 POSITION ERÖFFNET | %s\n", $1, signal, reason
        }
        /Öffne Short-Position/ {
            signal = "Verkauf"
            reason = $0
            printf "%s | %s | 🟢 POSITION ERÖFFNET | %s\n", $1, signal, reason
        }
        /Schließe .* Position/ {
            signal = ($4 == "long") ? "Long" : "Short"
            reason = $0
            printf "%s | %s | 🔴 POSITION GESCHLOSSEN | %s\n", $1, signal, reason
        }
    ' \
    | head -10
} | column -t -s "|"

# 5. Letzte Log-Einträge
print_header "LETZTE SYSTEMEREIGNISSE"
grep -v "TRADE_DECISION" "$LOG_FILE" | tail -n 15

# 6. Positionsstatus
print_header "AKTUELLE POSITIONEN"
position_line=$(grep -A 1 "Offene Position" "$LOG_FILE" | tail -1 | grep -v "Kontostand")
if [[ -n "$position_line" ]]; then
    echo "$position_line"
else
    echo "Keine aktiven Positionen"
fi

echo ""
echo "Überwachung abgeschlossen um $(date)"
