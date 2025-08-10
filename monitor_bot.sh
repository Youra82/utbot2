#!/bin/bash

# --- KONFIGURATION ---
# Pfad zur Log-Datei des Bots
LOG_FILE="/home/ubuntu/utbot2/logs/envelope.log"

# --- FUNKTIONEN ---

# Funktion, um Parameter aus der Log-Datei zu extrahieren und zu formatieren
function show_params() {
    echo "## Übersicht aller eingestellten Parameter"
    echo "----------------------------------------"
    # Extrahiert alle Parameter und ihre Werte aus der letzten Zusammenfassung
    awk '/--- MONITORING ZUSAMMENFASSUNG ---/{flag=1;next}/--- ENDE ZUSAMMENFASSUNG ---/{flag=0}flag' "$LOG_FILE" | grep -v 'Anzahl' | grep -v 'Kontostand' | grep -v 'Eingestellte'
}

# Funktion, um die Anzahl der Signale und Trades zu extrahieren
function show_stats() {
    echo "## Statistik"
    echo "------------------"
    # Extrahiert die Anzahl der erzeugten Signale
    SIGNALS=$(grep 'Anzahl erzeugter Signale im Lookback' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Anzahl der erzeugten Signale: ${SIGNALS:-0}"
    
    # Extrahiert die Gesamtzahl der Trades aus der letzten Zusammenfassung
    TRADES=$(grep 'Anzahl der Trades seit Beginn' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Anzahl der Trades: ${TRADES:-0}"
}

# Funktion, um den Kontostand zu extrahieren
function show_balance() {
    echo "## Kontostand"
    echo "------------------"
    # Extrahiert den aktuellen Kontostand
    BALANCE=$(grep 'Aktueller Kontostand' "$LOG_FILE" | tail -1 | awk -F': ' '{print $2}')
    echo "- Kontostand: ${BALANCE:-Nicht verfügbar}"
}

# Funktion, um detaillierte Gründe für fehlgeschlagene Trades zu extrahieren
function show_trade_reasons() {
    echo "## Detaillierte Handelsentscheidungen und Gründe"
    echo "----------------------------------------------"
    
    # Grep nach allen TRADE_DECISION-Einträgen
    # 'tail -50' zeigt die letzten 50 Entscheidungen an, um die Ausgabe übersichtlich zu halten
    DECISIONS=$(grep 'TRADE_DECISION' "$LOG_FILE" | tail -50)

    # Wenn keine Entscheidungen gefunden wurden
    if [ -z "$DECISIONS" ]; then
        echo "Keine Handelsentscheidungen im Log gefunden."
    else
        echo "$DECISIONS" | while read -r line; do
            # Entfernt das Präfix bis zum JSON-Objekt
            JSON_PART=$(echo "$line" | sed 's/.*TRADE_DECISION: //')
            
            # Formatiert die JSON-Ausgabe mit jq für bessere Lesbarkeit
            # Überprüft, ob das JSON-Objekt valide ist, bevor es verarbeitet wird
            if echo "$JSON_PART" | jq . &>/dev/null; then
                echo "---"
                TIMESTAMP=$(echo "$JSON_PART" | jq -r '.timestamp')
                SIGNAL=$(echo "$JSON_PART" | jq -r '.signal')
                DECISION=$(echo "$JSON_PART" | jq -r '.decision')
                DETAILS=$(echo "$JSON_PART" | jq -r '.details')

                echo "Zeitstempel: $TIMESTAMP"
                echo "Signal: $SIGNAL"
                echo "Entscheidung: $DECISION"
                
                # Prüft, ob es Details gibt und zeigt diese an
                if [ "$DETAILS" != "null" ] && [ "$DETAILS" != "" ]; then
                    echo "Details:"
                    # jq verwenden, um die Details als Schlüssel-Wert-Paare auszugeben
                    echo "$DETAILS" | jq -r 'to_entries[] | "  - \(.key): \(.value)"'
                fi
            fi
        done
        echo "---"
    fi
}

# --- HAUPTTEIL DES SKRIPTS ---

# Prüfen, ob die Log-Datei existiert
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
