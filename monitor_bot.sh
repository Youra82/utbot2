#!/bin/bash
# monitor_bot.sh - Überwacht den Status des Trading-Bots

# Konfiguration
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"
TRACKER_FILE="/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"  # Pfad anpassen
RUN_FILE="/home/ubuntu/utbot2/code/strategies/envelope/run.py"
SECRET_FILE="/home/ubuntu/utbot2/secret.json"

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
    echo "❌ Bot läuft NICHT!"
fi

# 2. Eingestellte Parameter anzeigen
print_header "AKTUELLE PARAMETER"
awk '/params = \{/,/^}/' "$RUN_FILE" | grep -vE "^ *#|^ *$" | sed 's/,$//'

# 3. API-Schlüsselstatus prüfen
print_header "API-SCHLÜSSELSTATUS"
if jq -e ".$key_name" "$SECRET_FILE" >/dev/null; then
    echo "✅ API-Schlüssel konfiguriert"
else
    echo "❌ Fehler: API-Schlüssel '$key_name' nicht gefunden!"
fi

# 4. Tracker-Status anzeigen
print_header "TRACKER-STATUS"
if [[ -f "$TRACKER_FILE" ]]; then
    jq . "$TRACKER_FILE"
else
    echo "Tracker-Datei nicht gefunden: $TRACKER_FILE"
fi

# 5. Signale und Handelsaktionen analysieren
print_header "SIGNALANALYSE"
{
    echo "Zeit | Signal | Aktion | Grund"
    echo "-----------------------------------------------"
    grep -E "Gefundene Signale|Verwende|Keine gültigen Signale|Signal abgelaufen|Öffne|Schließe|Status ist" "$LOG_FILE" \
    | tac \
    | awk '
        /Gefundene Signale/ {signals=$4; next}
        /Verwende/ {
            signal = ($2 == "Verwende") ? $3 : $2
            reason = ""
            for(i=($2=="Verwende"?4:3); i<=NF; i++) reason = reason $i " "
            printf "%s | %s | ✅ REAGIERT | %s\n", $1, signal, reason
        }
        /Keine gültigen Signale/ {
            printf "%s | - | ⚠️ KEINE SIGNALE | Keine gültigen Signale im Lookback-Periode\n", $1
        }
        /Signal abgelaufen/ {
            printf "%s | %s | ❌ IGNORIERT | Preisänderung zu groß\n", $1, $(NF-6)
        }
        /Status ist/ {
            status = $4
            sub(/,/, "", status)
            printf "%s | - | ❌ IGNORIERT | Tracker-Status: %s\n", $1, status
        }
        /Öffne/ {
            printf "%s | %s | 🟢 POSITION ERÖFFNET | %s\n", $1, ($3=="Long"?"Kauf":"Verkauf"), $0
        }
        /Schließe/ {
            printf "%s | %s | 🔴 POSITION GESCHLOSSEN | %s\n", $1, ($4=="long"?"Long":"Short"), $0
        }
    ' \
    | head -20
} | column -t -s "|"

# 6. Letzte Log-Einträge anzeigen
print_header "LETZTE LOG-EINTRÄGE"
tail -n 15 "$LOG_FILE"

# 7. Positionsstatus prüfen
print_header "AKTUELLE POSITIONEN"
positions=$(grep -A 2 "Offene Position" "$LOG_FILE" | tail -1)
if [[ -n "$positions" ]]; then
    echo "$positions"
else
    echo "Keine aktiven Positionen gefunden"
fi

echo ""
echo "Überwachung abgeschlossen um $(date)"
