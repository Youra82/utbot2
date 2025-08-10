#!/bin/bash

# --- KONFIGURATION ---
# Pfad zur Log-Datei des Bots
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"

# --- FUNKTIONEN ---

# Funktion, um Parameter aus der Log-Datei zu extrahieren und zu formatieren
function show_params() {
    echo "## Übersicht aller eingestellten Parameter"
    echo "----------------------------------------"
    # Sucht nach der letzten Zeile mit "Eingestellte Parameter:" und druckt die folgenden Zeilen
    # bis zur nächsten leeren Zeile oder einem ">>>" Zeichen
    awk '/Eingestellte Parameter:/,/^--- ENDE ZUSAMMENFASSUNG ---/{if($0!~/Eingestellte Parameter/ && $0!~/END/ && $0!~/^---/ && $0!~/^$/) print}' "$LOG_FILE" | tail -$(grep -c '^' "$LOG_FILE") | uniq | grep '^-'
}

# Funktion, um die Anzahl der Signale und Trades zu extrahieren
function show_stats() {
    echo "## Statistik"
    echo "------------------"
    SIGNALS=$(grep 'Anzahl erzeugter Signale im Lookback' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Anzahl der erzeugten Signale: ${SIGNALS:-0}"
    TRADES=$(grep 'Anzahl der Trades seit Beginn' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Anzahl der Trades: ${TRADES:-0}"
}

# Funktion, um den Kontostand zu extrahieren
function show_balance() {
    echo "## Kontostand"
    echo "------------------"
    BALANCE=$(grep 'Aktueller Kontostand' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Kontostand: ${BALANCE:-Nicht verfügbar}"
}

# Funktion, um detaillierte Gründe für fehlgeschlagene Trades zu extrahieren
function show_trade_reasons() {
    echo "## Detaillierte Handelsentscheidungen und Gründe"
    echo "----------------------------------------------"
    DECISIONS=$(grep 'TRADE_DECISION' "$LOG_FILE" | tail -50)
    if [ -z "$DECISIONS" ]; then
        echo "Keine Handelsentscheidungen im Log gefunden."
    else
        echo "$DECISIONS" | while read -r line; do
            JSON_PART=$(echo "$line" | sed 's/.*TRADE_DECISION: //')
            if echo "$JSON_PART" | jq . &>/dev/null; then
                echo "---"
                TIMESTAMP=$(echo "$JSON_PART" | jq -r '.timestamp')
                SIGNAL=$(echo "$JSON_PART" | jq -r '.signal')
                DECISION=$(echo "$JSON_PART" | jq -r '.decision')
                DETAILS=$(echo "$JSON_PART" | jq -r '.details')
                echo "Zeitstempel: $TIMESTAMP"
                echo "Signal: $SIGNAL"
                echo "Entscheidung: $DECISION"
                if [ "$DETAILS" != "null" ] && [ "$DETAILS" != "" ]; then
                    echo "Details:"
                    echo "$DETAILS" | jq -r 'to_entries[] | "  - \(.key): \(.value)"'
                fi
            fi
        done
        echo "---"
    fi
}

# --- HAUPTTEIL DES SKRIPTS ---

if [ ! -f "$LOG_FILE" ]; then
    echo "Fehler: Die Log-Datei '$LOG_FILE' wurde nicht gefunden."
    exit 1
fi

clear
echo "================================================="
echo "   Trading-Bot Monitor - Status für $(date +'%Y-%m-%d %H:%M:%S')"
echo "================================================="
echo ""

show_params
echo ""

show_stats
echo ""

show_balance
echo ""

show_trade_reasons
echo ""

echo "================================================="
