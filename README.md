#!/bin/bash
# monitor_bot.sh - Überwacht den Status des Trading-Bots mit erweiterten Details

# Konfiguration
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
TRACKER_FILE="/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"
RUN_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"
SECRET_FILE="/home/ubuntu/utbot2/secret.json"
PARAMS_FILE="/home/ubuntu/utbot2/code/strategies/envelope/params.json"

# Funktionen
print_header() {
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

# 1. Bot-Prozessstatus prüfen
print_header "BOT PROZESSSTATUS"
if pgrep -f "run.py" >/dev/null; then
    echo "✅ Bot läuft (PID: $(pgrep -f "run.py"))"
else
    echo "❌ Bot läuft NICHT! (Startbefehl: cd /home/ubuntu/utbot2/code/strategies/envelope && python3 run.py)"
fi

# 2. Eingestellte Parameter mit Beschreibungen anzeigen
print_header "AKTUELLE PARAMETER MIT BESCHREIBUNG"
if [ -f "$RUN_FILE" ]; then
    # Extrahiert Parameter mit Kommentaren
    awk '/params = \{/,/^}/' "$RUN_FILE" | grep -E '#|:' | while IFS= read -r line; do
        if [[ $line == *"#"* ]]; then
            # Kommentarzeile
            echo -e "\033[1;36m${line#*#}\033[0m"
        else
            # Parameterzeile
            IFS=':' read -r key value <<< "$line"
            key=$(echo "$key" | sed "s/'//g; s/ *//g")
            value=$(echo "$value" | sed "s/,$//; s/^ *//")
            echo -e "\033[1;33m$key\033[0m: \033[1;37m$value\033[0m"
        fi
    done
else
    echo "Run-Datei nicht gefunden: $RUN_FILE"
fi

# 3. API-Schlüsselstatus prüfen
print_header "API-SCHLÜSSELSTATUS"
if jq -e ".envelope" "$SECRET_FILE" >/dev/null; then
    echo "✅ API-Schlüssel konfiguriert"
else
    echo "❌ Fehler: API-Schlüssel 'envelope' nicht gefunden!"
fi

# 4. Tracker-Status anzeigen
print_header "TRACKER-STATUS"
if [[ -f "$TRACKER_FILE" ]]; then
    jq . "$TRACKER_FILE"
else
    echo "⚠️ Tracker-Datei nicht gefunden: $TRACKER_FILE"
    echo "Mögliche Ursachen:"
    echo "- Bot wurde noch nie erfolgreich ausgeführt"
    echo "- Symbolkonfiguration wurde geändert"
fi

# 5. Signale und Handelsaktionen analysieren
print_header "SIGNALANALYSE MIT PARAMETERGRÜNDEN"
{
    echo -e "Zeit | Signal | Aktion | Grund"
    echo "-----------------------------------------------"
    grep -E "Gefundene Signale|Verwende|Signalanalyse|Signal abgelaufen|ignoriert|Öffne|Schließe|Status ist" "$LOG_FILE" \
    | tac \
    | awk '
        /Gefundene Signale/ {signals=$4; next}
        /Signalanalyse abgeschlossen/ {
            reason = substr($0, index($0, "-") + 2)
            signal = $4
            printf "%s | %s | ℹ️ STATUS | %s\n", $1, signal, reason
        }
        /Verwende/ {
            signal = ($2 == "Verwende") ? $3 : $2
            reason = ""
            for(i=($2=="Verwende"?4:3); i<=NF; i++) reason = reason $i " "
            printf "%s | %s | ✅ REAGIERT | %s\n", $1, signal, reason
        }
        /Keine gültigen Signale/ {
            printf "%s | - | ⚠️ KEINE SIGNALE | Lookback-Periode: %d Kerzen\n", $1, '$(grep "signal_lookback_period" "$RUN_FILE" | awk -F: "{print \$2}" | tr -d ", ")'
        }
        /Signal abgelaufen/ {
            max_change = '$(grep "max_price_change_pct" "$RUN_FILE" | awk -F: "{print \$2}" | tr -d ", ")'
            printf "%s | %s | ❌ IGNORIERT | Aktuelle Änderung: %s > Max erlaubt: %s\n", $1, $(NF-6), $(NF-2), max_change
        }
        /ignoriert/ {
            if ($0 ~ /Long-Handel/) 
                printf "%s | BUY | ❌ IGNORIERT | Parameter: use_longs = %s\n", $1, "'$(
                    grep "use_longs" "$RUN_FILE" | awk -F: "{print \$2}" | tr -d ", "
                )'"
            else if ($0 ~ /Short-Handel/)
                printf "%s | SELL | ❌ IGNORIERT | Parameter: use_shorts = %s\n", $1, "'$(
                    grep "use_shorts" "$RUN_FILE" | awk -F: "{print \$2}" | tr -d ", "
                )'"
        }
        /Öffne/ {
            printf "%s | %s | 🟢 POSITION ERÖFFNET | %s\n", $1, ($3=="Long"?"Kauf":"Verkauf"), $0
        }
        /Schließe/ {
            printf "%s | %s | 🔴 POSITION GESCHLOSSEN | %s\n", $1, ($4=="long"?"Long":"Short"), $0
        }
        /Status ist/ {
            status = $4
            sub(/,/, "", status)
            printf "%s | - | ❌ IGNORIERT | Tracker-Status: %s\n", $1, status
        }
    ' \
    | head -20
} | column -t -s "|"

# 6. Positionsstatus prüfen
print_header "AKTUELLE MARKTPOSITION"
positions=$(grep -A 2 "Offene Position" "$LOG_FILE" | tail -1)
if [[ -n "$positions" ]]; then
    echo "$positions"
else
    echo "Keine aktiven Positionen in letzten Logs"
fi

# 7. Letzte Signale und Indikatoren
print_header "LETZTE SIGNALE & INDIKATOREN"
grep -A 10 "Letzte 10 Kerzen Signale und Indikatoren" "$LOG_FILE" | tail -n +2 | head -n 10

echo ""
echo -e "\033[1;35mÜberwachung abgeschlossen um $(date)\033[0m"
