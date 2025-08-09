#!/bin/bash

# monitor_bot.sh - Verbesserte Überwachung des Trading Bots

LOG_FILE="/home/ubuntu/utbot2/envelope.log"

echo "📊 BOT STATUS: $(date -u '+%H:%M:%S UTC')"
echo "----------------------------------------"

# 1. Letzte Handelsaktivitäten
echo "🚀 LETZTE HANDELS-AKTIONEN:"
grep -a -e "opened" -e "closed" -e "placed stop-loss" "$LOG_FILE" | tail -5 | sed 's/^/   /'

# 2. Signale und Positionen
echo ""
echo "📈 SIGNAL-STATUS:"

# Aktuelles Signal
last_signal=$(grep -a -e "using .* signal" -e "no valid signals" "$LOG_FILE" | tail -1)
if [[ -n "$last_signal" ]]; then
  echo "   ${last_signal:0:120}"
else
  echo "   Keine Signalinformationen gefunden"
fi

# Aktive Position
active_position=$(grep -a "open .* position" "$LOG_FILE" | tail -1)
if [[ -n "$active_position" ]]; then
  echo "   🟢 AKTIVE POSITION: ${active_position:0:100}"
else
  echo "   🔴 KEINE AKTIVE POSITION"
fi

# 3. Systemstatus
echo ""
echo "⚙️ SYSTEM-STATUS:"

# Letzte Ausführung
last_exec=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2}')
if [[ -n "$last_exec" ]]; then
  echo "   Letzte Ausführung: $last_exec UTC"
  
  # Nächste Ausführung
  cron_job=$(crontab -l | grep "run_envelope.sh")
  if [[ "$cron_job" == *"*/15"* ]]; then
    last_min=${last_exec:3:2}
    next_min=$(( (10#$last_min + 15) % 60 ))
    next_hour=$(( 10#${last_exec:0:2} + (10#$last_min + 15) / 60 ))
    next_hour=$((next_hour % 24))
    printf "   Nächste Ausführung: %02d:%02d UTC\n" $next_hour $next_min
  fi
fi

# Log-Zustand
log_entries=$(wc -l < "$LOG_FILE")
log_size=$(du -h "$LOG_FILE" | cut -f1)
echo "   Log-Einträge: $log_entries | Größe: $log_size"

# 4. Performance-Statistiken
echo ""
echo "💹 PERFORMANCE-STATS:"

# Signale in letzter Zeit
signals_count=$(grep -a -e "found [0-9]\+ signals" "$LOG_FILE" | tail -4 | grep -o "found [0-9]\+" | awk '{sum += $2} END {print sum}')
echo "   Signale (letzte 4 Runs): $signals_count"

# Trades heute
today=$(date -u '+%Y-%m-%d')
trades_today=$(grep -a -e "opened" -e "closed" "$LOG_FILE" | grep "$today" | wc -l)
echo "   Trades heute: $trades_today"

# Offene Orders
open_orders=$(grep -a "all orders cancelled" "$LOG_FILE" | tail -1 | awk -F: '{print $2}')
if [[ -n "$open_orders" ]]; then
  echo "   Offene Orders nach Reset: $open_orders"
fi

echo "----------------------------------------"
echo "ℹ️ Verwende 'tail -f $LOG_FILE' für Echtzeit-Logs"
