#!/bin/bash

# monitor_strategy.sh - Fokussiert auf Strategieperformance

LOG_FILE="/home/ubuntu/utbot2/envelope.log"
RUN_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"

# 1. Strategieeinstellungen
echo "⚙️ STRATEGIEKONFIGURATION:"
grep -E "'(symbol|timeframe|leverage|trade_size_pct|stop_loss_pct|enable_stop_loss|signal_lookback_period)'" "$RUN_FILE" | 
  sed "s/.*'\([^']*\)': \([^,]*\).*/\1: \2/" | 
  sed 's/True/Aktiviert/;s/False/Deaktiviert/;s/^/   /'

# 2. Handelsstatus
echo ""
echo "📈 HANDELSSTATUS:"

# Letzte Handelsaktion
last_trade=$(grep -a -e "opened" -e "closed" "$LOG_FILE" | tail -1)
if [[ -n "$last_trade" ]]; then
  echo "   Letzte Aktion: ${last_trade:0:100}"
else
  echo "   Keine Handelsaktivitäten"
fi

# Aktiver Trade
active_position=$(grep -a "open .* position" "$LOG_FILE" | tail -1)
if [[ -n "$active_position" ]]; then
  echo "   🟢 Aktive Position: ${active_position:0:100}"
else
  echo "   🔴 Keine aktive Position"
fi

# 3. Signalanalyse
echo ""
echo "📡 SIGNALANALYSE:"

# Signale der letzten Ausführungen
echo "   Letzte Signalprüfungen:"
grep -a -e "UTC: found" -e "UTC: using" "$LOG_FILE" | tail -3 | sed 's/^/      /'

# Signalstatistik
total_signals=$(grep -a "UTC: found" "$LOG_FILE" | awk '{sum += $5} END {print sum}')
profitable_signals=$(grep -a "UTC: using" "$LOG_FILE" | grep "profit" | wc -l)
echo "   Signale (heute): $total_signals"
if [[ $total_signals -gt 0 ]]; then
  success_rate=$((profitable_signals * 100 / total_signals))
  echo "   Erfolgsquote: $success_rate%"
fi

# 4. Systembetrieb
echo ""
echo "⏱ SYSTEMBETRIEB:"

# Cron-Job Status
cron_job=$(crontab -l | grep "run_envelope.sh")
if [[ -n "$cron_job" ]]; then
  echo "   ✅ Cron-Job aktiv:"
  echo "      $cron_job"
  
  # Nächste Ausführung
  last_run=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | grep -oE '[0-9]{2}:[0-9]{2}')
  if [[ -n "$last_run" ]]; then
    last_min=${last_run:3:2}
    next_min=$(( (10#$last_min + 15) % 60 ))
    next_hour=$((10#${last_run:0:2} + (10#$last_min + 15)/60))
    printf "   Nächste Ausführung ~: %02d:%02d UTC\n" $((next_hour % 24)) $next_min
  fi
else
  echo "   ❌ Cron-Job nicht konfiguriert!"
fi

# Letzte Ausführung
last_execution=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | cut -c 1-100)
echo "   Letzte Ausführung: ${last_execution}"
