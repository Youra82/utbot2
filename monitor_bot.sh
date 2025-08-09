#!/bin/bash

# monitor_envelope.sh - Überwachung des Envelope Trading Bots

LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"  # Pfad zur Log-Datei anpassen
TRACKER_FILE="/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"  # Pfad zur Tracker-Datei

echo "📊 ENVELOPE BOT STATUS: $(date -u '+%H:%M:%S UTC')"
echo "----------------------------------------"

# 1. Bot-Aktivitäten
echo "🚀 LETZTE BOT-AKTIONEN:"
grep -a -e ">>> starting execution" -e "<<< execution complete" -e "opened" -e "closed" -e "cancelled" "$LOG_FILE" | tail -5 | sed 's/^/   /'

# 2. Signalanalyse
echo ""
echo "📈 SIGNAL-STATUS:"

# Letzte Signalberechnung
last_signal=$(grep -a "using .* signal" "$LOG_FILE" | tail -1)
if [[ -n "$last_signal" ]]; then
  echo "   ${last_signal:0:100}"
else
  echo "   Keine aktiven Signale in letzter Ausführung"
fi

# Kerzendaten
last_candle=$(grep -a "Last [0-9]\+ candles signals:" -A 6 "$LOG_FILE" | tail -6)
if [[ -n "$last_candle" ]]; then
  echo "   Letzte Kerzendaten:"
  echo "$last_candle" | sed 's/^/      /'
fi

# 3. Positionsstatus
echo ""
echo "💰 POSITIONS-STATUS:"

# Tracker-Datei auslesen
if [[ -f "$TRACKER_FILE" ]]; then
  tracker_data=$(jq -c '.' "$TRACKER_FILE" 2>/dev/null)
  if [[ -n "$tracker_data" ]]; then
    status=$(jq -r '.status' <<< "$tracker_data")
    last_side=$(jq -r '.last_side' <<< "$tracker_data")
    stop_loss_ids=$(jq -r '.stop_loss_ids | length' <<< "$tracker_data")
    
    echo "   Status: $status"
    echo "   Letzte Position: $last_side"
    echo "   Aktive Stop-Loss Orders: $stop_loss_ids"
  else
    echo "   Fehler beim Lesen der Tracker-Datei"
  fi
else
  echo "   Tracker-Datei nicht gefunden"
fi

# Offene Positionen
position_info=$(grep -a "open .* position" "$LOG_FILE" | tail -1)
if [[ -n "$position_info" ]]; then
  echo "   🟢 AKTIVE POSITION: ${position_info:0:80}"
else
  echo "   🔴 KEINE AKTIVE POSITION"
fi

# 4. Systemstatus
echo ""
echo "⚙️ SYSTEM-STATUS:"

# Letzte Ausführung
last_exec=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2}')
if [[ -n "$last_exec" ]]; then
  echo "   Letzte Ausführung: $last_exec UTC"
  
  # Nächste Ausführung berechnen (15m Intervall)
  last_min=${last_exec:3:2}
  next_min=$(( (10#$last_min + 15) % 60 ))
  next_hour=$(( 10#${last_exec:0:2} + (10#$last_min + 15) / 60 ))
  next_hour=$((next_hour % 24))
  printf "   Nächste Ausführung: %02d:%02d UTC\n" $next_hour $next_min
fi

# Log-Zustand
if [[ -f "$LOG_FILE" ]]; then
  log_entries=$(wc -l < "$LOG_FILE" 2>/dev/null)
  log_size=$(du -h "$LOG_FILE" | cut -f1)
  echo "   Log-Einträge: $log_entries | Größe: $log_size"
else
  echo "   Log-Datei nicht gefunden"
fi

# 5. Performance-Statistiken
echo ""
echo "💹 PERFORMANCE-STATS:"

# Signale in letzter Zeit
signals_today=$(grep -a "found [0-9]\+ signals" "$LOG_FILE" | grep "$(date -u '+%Y-%m-%d')" | awk '{sum += $8} END {print sum}')
echo "   Signale heute: ${signals_today:-0}"

# Trades heute
trades_today=$(grep -a -e "opened" -e "closed" "$LOG_FILE" | grep "$(date -u '+%Y-%m-%d')" | wc -l)
echo "   Trades heute: $trades_today"

echo "----------------------------------------"
echo "ℹ️ Verwende 'tail -f $LOG_FILE' für Echtzeit-Logs"
