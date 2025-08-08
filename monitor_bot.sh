#!/bin/bash

# monitor_strategy.sh - Zeigt aktuelle Strategieeinstellungen und Handelsaktivitäten

LOG_FILE="/home/ubuntu/utbot2/envelope.log"
RUN_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"

# 1. Aktuelle Strategieeinstellungen anzeigen
echo "⚙️ AKTUELLE STRATEGIE-EINSTELLUNGEN:"

# Extrahiere wichtige Parameter
params_to_display=(
    "symbol" "timeframe" "leverage" "trade_size_pct" 
    "stop_loss_pct" "enable_stop_loss" "ut_heiken_ashi"
    "signal_lookback_period" "min_signal_confirmation" "max_price_change_pct"
)

for param in "${params_to_display[@]}"; do
    value=$(grep -oP "'$param': \K[^,]+" "$RUN_FILE" | head -1)
    # Sonderbehandlung für boolesche Werte
    if [[ "$value" == "True" || "$value" == "False" ]]; then
        value=$(echo "$value" | sed 's/True/Aktiviert/;s/False/Deaktiviert/')
    fi
    printf "   %-25s: %s\n" "$param" "$value"
done

# 2. Letzte Signale und Handelsaktivitäten
echo ""
echo "📈 LETZTE SIGNALE UND AKTIVITÄTEN:"

# Signale der letzten 3 Ausführungen
echo "   Letzte Signale:"
grep -a -e "UTC: found" -e "UTC: using" "$LOG_FILE" | tail -3 | sed 's/^/      /'

# Aktuelle Position
last_position=$(grep -a "open .* position" "$LOG_FILE" | tail -1)
if [[ -n "$last_position" ]]; then
    echo "   🟢 Aktive Position: ${last_position:0:100}"
else
    echo "   🔴 Keine aktive Position"
fi

# Letzte Handelsaktionen
echo "   Letzte Aktionen:"
grep -a -e "opened" -e "closed" -e "placed stop-loss" "$LOG_FILE" | tail -3 | sed 's/^/      /'

# 3. Statistiken
echo ""
echo "📊 HANDELSSTATISTIK (LETZTE 24 STUNDEN):"

# Anzahl der Signale
signals_count=$(grep -a "UTC: found" "$LOG_FILE" | grep -v "0 signals" | wc -l)
echo "   Signale: $signals_count"

# Anzahl der Trades
trades_count=$(grep -a -e "opened" -e "closed" "$LOG_FILE" | wc -l)
echo "   Trades: $trades_count"

# Erfolgsquote
win_count=$(grep -a "closed .* profit" "$LOG_FILE" | wc -l)
if [[ $trades_count -gt 0 ]]; then
    win_rate=$((win_count * 100 / trades_count))
    echo "   Erfolgsquote: $win_rate%"
else
    echo "   Erfolgsquote: Keine Trades"
fi

# 4. Systemstatus
echo ""
echo "🖥 SYSTEMSTATUS:"

# Letzte Ausführung
last_run=$(grep -a ">>> starting execution" "$LOG_FILE" | tail -1 | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2}')
if [[ -n "$last_run" ]]; then
    echo "   Letzte Ausführung: $last_run UTC"
    
    # Nächste Ausführung
    cron_job=$(crontab -l | grep "run_envelope.sh")
    if [[ "$cron_job" == *"*/15"* ]]; then
        last_min=${last_run:3:2}
        next_min=$(( ( (last_min + 15) % 60 )))
        next_hour=$(( 10#${last_run:0:2} + (last_min + 15) / 60 ))
        printf "   Nächste Ausführung ca.: %02d:%02d UTC\n" $((next_hour % 24)) $next_min
    fi
else
    echo "   Keine Ausführungsdaten"
fi

# Bot-Prozessstatus
if pgrep -f "$RUN_FILE" > /dev/null; then
    echo "   🟢 Bot läuft (PID: $(pgrep -f "$RUN_FILE"))"
else
    echo "   🔴 Bot nicht aktiv"
fi
