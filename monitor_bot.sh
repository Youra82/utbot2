#!/bin/bash

# monitor_bot.sh - Überwacht Trades und Signale des Trading Bots

LOG_FILE="/home/ubuntu/utbot2/envelope.log"

# 1. Letzte Handelsaktivitäten
echo "📊 LETZTE HANDELS-AKTIVITÄTEN:"
grep -a -e "opened" -e "closed" -e "placed stop-loss" "$LOG_FILE" | tail -5 | sed 's/^/   /'

# 2. Signale und Positionen
echo ""
echo "📈 SIGNALE UND POSITIONEN:"

# Aktuelles Signal
last_signal=$(grep -a -e "using .* signal" -e "no valid signals" "$LOG_FILE" | tail -1)
if [[ -n "$last_signal" ]]; then
  echo "   Letztes Signal: ${last_signal:0:100}"
else
  echo "   Keine Signalinformationen gefunden"
fi

# Letzte Position
last_position=$(grep -a "open .* position" "$LOG_FILE" | tail -1)
if [[ -n "$last_position" ]]; then
  echo "   Letzte Position: ${last_position:0:100}"
else
  echo "   Keine aktive Position"
fi

# 3. Handelsstatistik
echo ""
echo "💹 HANDELSSTATISTIK:"

# Signale in letzter Stunde
signals_count=$(grep -a -e "found [0-9]\+ signals" "$LOG_FILE" | tail -4 | grep -o "found [0-9]\+" | awk '{sum += $2} END {print sum}')
echo "   Signale (letzte 4 Runs): $signals_count"

# Trades in letzter Stunde
trades_count=$(grep -a -e "opened" -e "closed" "$LOG_FILE" | tail -10 | wc -l)
echo "   Trades (letzte 10 Einträge): $trades_count"

# 4. Zeitliche Übersicht
echo ""
echo "⏱ ZEITLICHE ÜBERSICHT:"

# Letzte Ausführung
last_exec_time=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2}')
if [[ -n "$last_exec_time" ]]; then
  echo "   Letzte Ausführung: $last_exec_time UTC"
  
  # Nächste geplante Ausführung
  cron_job=$(crontab -l | grep "run_envelope.sh")
  if [[ "$cron_job" == *"*/15"* ]]; then
    last_min=${last_exec_time:3:2}
    next_min=$(( ( (last_min + 15) % 60 )))
    next_hour=$(( 10#${last_exec_time:0:2} + (last_min + 15) / 60 ))
    printf "   Nächste Ausführung ca.: %02d:%02d UTC\n" $((next_hour % 24)) $next_min
  fi
else
  echo "   Keine Ausführungsdaten gefunden"
fi
