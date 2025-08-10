#!/bin/bash
# monitor_bot.sh - Erweiterte Überwachung des Trading-Bots

LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
TRACKER_FILE="/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"

print_header() {
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

# 1. Strategieparameter inkl. Erklärung
print_header "STRATEGIEPARAMETER"
grep "Strategieparameter:" "$LOG_FILE" | tail -1 | sed 's/Strategieparameter: //'

# 2. Anzahl der erzeugten Signale (letzte Ausführung)
print_header "ANZAHL SIGNATUREN"
signals_line=$(grep "Gefundene Signale" "$LOG_FILE" | tail -1)
signals=$(echo "$signals_line" | sed 's/.*Gefundene Signale: //')
echo "Signale (letzte Ausführung): ${signals:-0}"

# 3. Anzahl der Trades (erfolgreiche Trade-Ausführungen)
print_header "ANZAHL TRADES"
trade_count=$(grep -c "\"decision\": \"Trade ausgeführt\"" "$LOG_FILE")
echo "Trades insgesamt: $trade_count"

# 4. Aktueller Kontostand aus Tracker
print_header "AKTUELLER KONTOSTAND (aus Tracker)"
if [ -f "$TRACKER_FILE" ]; then
    kontostand=$(jq -r '.kontostand // empty' "$TRACKER_FILE")
    if [ -n "$kontostand" ]; then
        echo "Kontostand laut Tracker: $kontostand USDT"
    else
        echo "Kontostand nicht im Tracker verfügbar"
    fi
else
    echo "Tracker-Datei nicht gefunden"
fi

# 5. Detaillierte Gründe für nicht ausgeführte Trades (letzte 20)
print_header "GRÜNDE FÜR NICHT AUSGEFÜHRTE TRADES (letzte 20)"
grep "Trade abgelehnt" "$LOG_FILE" | tail -20 | while read -r line; do
    json_part=$(echo "$line" | sed 's/.*TRADE_DECISION: //')
    timestamp=$(echo "$json_part" | jq -r '.timestamp')
    signal=$(echo "$json_part" | jq -r '.signal')
    details=$(echo "$json_part" | jq -r '.details')
    echo "[$timestamp] Signal: $signal | Grund: $details"
done

# 6. Info zu Mindest-Tradegröße und Hebel (falls in Logs vorhanden)
print_header "MINDEST-TRADEGRÖSSE & HEBEL-INFO"
grep "Handelsgröße-Info" "$LOG_FILE" | tail -5
grep "empfohlener Hebel" "$LOG_FILE" | tail -5

# 7. Aktuelle offene Position (aus Tracker, falls vorhanden)
print_header "AKTUELLE POSITIONEN (aus Tracker)"
if [ -f "$TRACKER_FILE" ]; then
    letzte_pos=$(jq -r '.letzte_position // empty' "$TRACKER_FILE")
    if [ -n "$letzte_pos" ]; then
        zeit=$(echo "$letzte_pos" | jq -r '.zeit')
        signal=$(echo "$letzte_pos" | jq -r '.signal')
        groesse=$(echo "$letzte_pos" | jq -r '.positionsgroesse')
        echo "Letzte Position: Zeit=$zeit | Signal=$signal | Positionsgröße=${groesse} BTC"
    else
        echo "Keine aktive Position im Tracker gefunden"
    fi
else
    echo "Tracker-Datei nicht gefunden"
fi

# 8. Letzte 15 System-Logeinträge (ohne Trade-Entscheidungen)
print_header "LETZTE SYSTEMEREIGNISSE (ohne Trade-Entscheidungen)"
grep -v "TRADE_DECISION" "$LOG_FILE" | tail -15

echo ""
echo "Überwachung abgeschlossen um $(date)"
