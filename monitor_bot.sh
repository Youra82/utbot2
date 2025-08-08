#!/bin/bash

# monitor_bot.sh - Überwacht den Trading Bot

BOT_PATH="/home/ubuntu/utbot2/code/strategies/envelope/run_btc.py"
LOG_FILE="/home/ubuntu/utbot2/envelope.log"
ERROR_KEYWORDS=("Traceback" "Exception" "Error" "Failed" "timed out" "candle" "IndexError" "KeyError")

# 1. Prüfe laufende Prozesse
if pgrep -f "$BOT_PATH" > /dev/null; then
  echo "✅ Bot-Prozess läuft (PID: $(pgrep -f "$BOT_PATH"))"
else
  echo "❌ Bot-Prozess läuft NICHT!"
fi

# 2. Prüfe letzte Ausführung
last_execution=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1)
if [[ -n "$last_execution" ]]; then
  execution_time=$(echo "$last_execution" | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2} UTC')
  echo "⏱ Letzte Ausführung: $execution_time UTC"
  
  # Berechne Zeit seit letzter Ausführung
  current_time_utc=$(date -u +%s)
  last_time_utc=$(date -u -d "${execution_time:0:8}" +%s 2>/dev/null)
  
  if [[ -n "$last_time_utc" ]]; then
    seconds_since=$((current_time_utc - last_time_utc))
    minutes_since=$((seconds_since / 60))
    
    if [[ $minutes_since -gt 20 ]]; then
      echo "⚠️ Achtung: Letzte Ausführung vor $minutes_since Minuten!"
    else
      echo "🟢 Vor $minutes_since Minuten"
    fi
  fi
else
  echo "⚠️ Keine Ausführungen im Log gefunden!"
fi

# 3. Prüfe auf Fehler in den letzten 20 Minuten
recent_log=$(grep -a -A 10 -B 10 "$(date -u -d '20 minutes ago' '+%H:%M')" "$LOG_FILE")
found_errors=0

for keyword in "${ERROR_KEYWORDS[@]}"; do
  if grep -a -i "$keyword" <<< "$recent_log" | grep -v ">>> starting execution" > /dev/null; then
    found_errors=1
    echo "🔥 FEHLER GEFUNDEN ('$keyword'):"
    grep -a -i -C 2 "$keyword" <<< "$recent_log"
  fi
done

if [[ $found_errors -eq 0 ]]; then
  echo "✅ Keine kritischen Fehler in den letzten 20 Minuten"
fi

# 4. Prüfe Cron-Job
cron_status=$(crontab -l | grep "run_envelope.sh")
if [[ -n "$cron_status" ]]; then
  echo "⏲️ Cron-Job aktiviert:"
  crontab -l | grep "run_envelope.sh"
  
  # Prüfe Intervall
  if [[ "$cron_status" == *"*/15"* ]]; then
    echo "   ✅ Konfiguration: Alle 15 Minuten"
  else
    echo "   ⚠️ ACHTUNG: Nicht 15-Minuten-Intervall!"
  fi
else
  echo "⚠️ Cron-Job NICHT konfiguriert!"
fi

# 5. Prüfe Handelsaktivitäten
echo "📊 Letzte Handelsaktivitäten:"
grep -a -e "opened" -e "closed" -e "placed stop-loss" -e "signal" "$LOG_FILE" | tail -5

# 6. Prüfe Guthaben
balance_info=$(grep -a "available balance" "$LOG_FILE" | tail -1)
if [[ -n "$balance_info" ]]; then
  echo "💰 Letztes Guthaben:"
  echo "   $balance_info"
fi

# 7. Signale prüfen
last_signals=$(grep -a -e "found [0-9]\+ signals" -e "using .* signal" "$LOG_FILE" | tail -3)
if [[ -n "$last_signals" ]]; then
  echo "📈 Letzte Signale:"
  echo "$last_signals"
fi
