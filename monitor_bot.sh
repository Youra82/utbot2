#!/bin/bash

BOT_PATH="/home/ubuntu/utbot2/code/strategies/envelope/run.py"
LOG_FILE="/home/ubuntu/utbot2/envelope.log"
ERROR_KEYWORDS=("Traceback" "Exception" "Error" "Failed" "timed out" "credential")

# API-Key spezifische Prüfung
check_api_key() {
    if grep -q "apiKey" "$LOG_FILE"; then
        echo "🔥 KRITISCHER FEHLER: API-Key Problem erkannt"
        grep -A 5 -B 2 "apiKey" "$LOG_FILE"
        
        # Lösungsvorschläge
        echo "🛠️ Mögliche Lösungen:"
        echo "1. Prüfen Sie die Existenz der secret.json: ls -l utbot2/secret.json"
        echo "2. Überprüfen Sie den Inhalt: cat utbot2/secret.json"
        echo "3. Setzen Sie Berechtigungen: chmod 600 utbot2/secret.json"
        return 1
    fi
    return 0
}

# 1. Prüfe API-Key Probleme
if ! check_api_key; then
    exit 1
fi

# 2. Prüfe laufende Prozesse
if pgrep -f "$BOT_PATH" > /dev/null; then
    echo "✅ Bot-Prozess läuft (PID: $(pgrep -f "$BOT_PATH"))"
else
    echo "❌ Bot-Prozess läuft NICHT!"
fi

# 3. Prüfe letzte Ausführung
last_execution=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1)
if [[ -n "$last_execution" ]]; then
    echo "⏱ Letzte Ausführung: ${last_execution:0:100}"
    
    # Extrahiere UTC-Zeit
    execution_time=$(echo "$last_execution" | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2} UTC')
    
    if [[ -n "$execution_time" ]]; then
        current_seconds=$(date -u +%s)
        execution_seconds=$(date -u -d "$execution_time" +%s)
        seconds_diff=$((current_seconds - execution_seconds))
        
        if (( seconds_diff > 900 )); then
            echo "⚠️ ACHTUNG: Letzte Ausführung vor $((seconds_diff/60)) Minuten!"
        else
            echo "🟢 Vor $((seconds_diff/60)) Minuten"
        fi
    fi
else
    echo "⚠️ Keine Ausführungen im Log gefunden!"
fi

# 4. Prüfe auf Fehler
found_errors=0
for keyword in "${ERROR_KEYWORDS[@]}"; do
    if grep -q -a -i "$keyword" "$LOG_FILE"; then
        found_errors=1
        echo "🔥 FEHLER GEFUNDEN ('$keyword'):"
        grep -a -i -C 3 "$keyword" "$LOG_FILE" | tail -15
        break
    fi
done

if [[ $found_errors -eq 0 ]]; then
    echo "✅ Keine kritischen Fehler gefunden"
fi

# 5. Cron-Job Analyse
echo "⏲️ Cron-Job Status:"
crontab -l | grep "run_envelope.sh" | while read -r line; do
    if [[ "$line" == *"LiveTradingBots"* ]]; then
        echo "   ⚠️ VERALTET: $line"
    elif [[ "$line" == *"utbot2"* ]]; then
        echo "   ✅ AKTIV: $line"
    else
        echo "   ❓ UNBEKANNT: $line"
    fi
done

# 6. Ressourcenüberwachung
echo "💻 Systemressourcen:"
echo " - CPU: $(top -bn1 | grep load | awk '{printf "%.2f\n", $(NF-2)}')"
echo " - RAM: $(free -m | awk '/Mem:/ {printf "%.1f%%\n", $3/$2*100}')"
