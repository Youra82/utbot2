#!/bin/bash

# monitor_bot.sh - Überwacht den Trading Bot

BOT_PATH="/home/ubuntu/utbot2/code/strategies/envelope/run.py"
LOG_FILE="/home/ubuntu/utbot2/envelope.log"
ERROR_KEYWORDS=("Traceback" "Exception" "Error" "Failed" "timed out")

# 1. Prüfe laufende Prozesse
if pgrep -f "$BOT_PATH" > /dev/null; then
  echo "✅ Bot-Prozess läuft (PID: $(pgrep -f "$BOT_PATH"))"
else
  echo "❌ Bot-Prozess läuft NICHT!"
fi

# 2. Prüfe Log-Aktivität
last_run=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1)
if [[ -n "$last_run" ]]; then
  echo "⏱ Letzte Ausführung: ${last_run:0:50}"
else
  echo "⚠️ Keine Ausführungen im Log gefunden!"
fi

# 3. Prüfe auf Fehler in den letzten 15 Minuten
recent_errors=$(grep -a -i -C 2 "$(date -d '15 minutes ago' '+%H:%M')" "$LOG_FILE")
found_errors=0

for keyword in "${ERROR_KEYWORDS[@]}"; do
  if grep -a -q -i "$keyword" <<< "$recent_errors"; then
    found_errors=1
    echo "🔥 FEHLER GEFUNDEN:"
    grep -a -i -C 2 "$keyword" <<< "$recent_errors"
  fi
done

if [[ $found_errors -eq 0 ]]; then
  echo "✅ Keine kritischen Fehler in den letzten 15 Minuten"
fi

# 4. Prüfe Cron-Job
cron_status=$(crontab -l | grep "run_envelope.sh")
if [[ -n "$cron_status" ]]; then
  echo "⏲️ Cron-Job aktiviert:"
  echo "   $cron_status"
else
  echo "⚠️ Cron-Job NICHT konfiguriert!"
fi

# 5. Prüfe letzte Positionen
last_positions=$(grep -a -e "position" -e "orders" "$LOG_FILE" | tail -5)
if [[ -n "$last_positions" ]]; then
  echo "📊 Letzte Positionen/Orders:"
  echo "$last_positions"
fi
