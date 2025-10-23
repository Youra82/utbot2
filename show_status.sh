#!/bin/bash

# Farben
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Hauptverzeichnis
PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# Funktion zum Anzeigen von Dateien
show_file_content() {
    FILE_PATH=$1
    # Korrigiert: Verwende den relativen Pfad für die Beschreibung
    RELATIVE_PATH=${FILE_PATH#"$PROJECT_ROOT/"}
    DESCRIPTION=$(basename "$FILE_PATH")

    if [ -f "$FILE_PATH" ]; then
        echo -e "\n${BLUE}======================================================================${NC}"
        echo -e "${YELLOW}DATEI: ${DESCRIPTION}${NC}"
        # Korrigiert: Zeige den relativen Pfad an
        echo -e "${CYAN}Pfad: ${RELATIVE_PATH}${NC}"
        echo -e "${BLUE}----------------------------------------------------------------------${NC}"

        # Zensur für secret.json (angepasst an utbot2)
        if [[ "$DESCRIPTION" == "secret.json" ]]; then
            echo -e "${YELLOW}HINWEIS: Sensible Daten in secret.json wurden zensiert.${NC}"
            sed -E 's/("apiKey"|"secret"|"password"|"bot_token"|"chat_id"|"api_key"): ".*"/"\1": "[ZENSIERT]"/g' "$FILE_PATH" | cat -n
        # Zensur für open_trades.json (optional, aber sinnvoll)
        elif [[ "$DESCRIPTION" == "open_trades.json" ]]; then
             echo -e "${YELLOW}HINWEIS: Details offener Trades in open_trades.json sind Platzhalter.${NC}"
             echo "[Inhalt von open_trades.json wird hier nicht angezeigt]"
        else
            cat -n "$FILE_PATH"
        fi
        echo -e "${BLUE}======================================================================${NC}"
    else
        echo -e "\n${RED}WARNUNG: Datei nicht gefunden: ${FILE_PATH}${NC}"
    fi
}

# --- ANZEIGE ALLER RELEVANTEN CODE-DATEIEN ---
echo -e "${BLUE}======================================================================${NC}"
echo "              Vollständige Code-Dokumentation des utbot2"
echo -e "${BLUE}======================================================================${NC}"

# Finde alle relevanten Dateien, schließe sensible/generierte/große Verzeichnisse aus
# Zeige secret.json und open_trades.json am Ende
mapfile -t FILE_LIST < <(find "$PROJECT_ROOT" -path "$PROJECT_ROOT/.venv" -prune \
                                             -o -path "$PROJECT_ROOT/logs" -prune \
                                             -o -path "$PROJECT_ROOT/.git" -prune \
                                             -o -path '*/__pycache__' -prune \
                                             -o -name 'secret.json' -prune \
                                             -o -name 'open_trades.json' -prune \
                                             -o \( -name "*.py" -o -name "*.sh" -o -name "*.json" -o -name "*.toml" -o -name "*.txt" -o -name ".gitignore" \) -print | sort)

# Zeige alle anderen Dateien
for filepath in "${FILE_LIST[@]}"; do
    # Stelle sicher, dass wir nicht versehentlich doch die ausgeschlossenen Dateien anzeigen
    if [[ "$(basename "$filepath")" != "secret.json" && "$(basename "$filepath")" != "open_trades.json" ]]; then
        show_file_content "$filepath"
    fi
done

# Zeige open_trades.json (zensiert) und secret.json (zensiert) als Letzte
show_file_content "$PROJECT_ROOT/open_trades.json"
show_file_content "$PROJECT_ROOT/secret.json"


# --- ANZEIGE DER PROJEKTSTRUKTUR ---
echo -e "\n\n${BLUE}======================================================="
echo "                 Aktuelle Projektstruktur"
echo -e "=======================================================${NC}"

# Strukturansicht (angepasst für utbot2)
list_structure() {
    find "$PROJECT_ROOT" -maxdepth 3 -path "$PROJECT_ROOT/.venv" -prune \
                         -o -path "$PROJECT_ROOT/logs" -prune \
                         -o -path "$PROJECT_ROOT/.git" -prune \
                         -o -path '*/__pycache__' -prune \
                         -o -print | sed -e "s;$PROJECT_ROOT;.;" -e 's;[^/]*/;|____;g;s;____|; |;g'
}

list_structure

echo -e "${BLUE}=======================================================${NC}"
