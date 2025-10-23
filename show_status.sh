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
    DESCRIPTION=$(basename "$FILE_PATH")

    if [ -f "$FILE_PATH" ]; then
        echo -e "\n${BLUE}======================================================================${NC}"
        echo -e "${YELLOW}DATEI: ${DESCRIPTION}${NC}"
        echo -e "${CYAN}Pfad: ${FILE_PATH}${NC}" # Zeigt den vollen Pfad an
        echo -e "${BLUE}----------------------------------------------------------------------${NC}"

        # Zensur für secret.json
        if [[ "$DESCRIPTION" == "secret.json" ]]; then
            echo -e "${YELLOW}HINWEIS: Sensible Daten in secret.json wurden zensiert.${NC}"
            # Passt die Zensur an die Schlüssel in utbot2's secret.json an
            sed -E 's/("apiKey"|"secret"|"password"|"bot_token"|"chat_id"|"api_key"): ".*"/"\1": "[ZENSIERT]"/g' "$FILE_PATH" | cat -n
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

# Finde alle relevanten Dateien, schließe .venv und __pycache__ aus, aber zeige secret.json am Ende
mapfile -t FILE_LIST < <(find "$PROJECT_ROOT" -path "$PROJECT_ROOT/.venv" -prune -o -path "$PROJECT_ROOT/logs" -prune -o -path "$PROJECT_ROOT/.git" -prune -o -path '*/__pycache__' -prune -o -name 'secret.json' -prune -o \( -name "*.py" -o -name "*.sh" -o -name "*.json" -o -name "*.toml" -o -name "*.txt" -o -name ".gitignore" \) -print | sort)

# Zeige alle Dateien außer secret.json
for filepath in "${FILE_LIST[@]}"; do
    show_file_content "$filepath"
done

# Zeige secret.json als Letztes
show_file_content "$PROJECT_ROOT/secret.json"

# --- ANZEIGE DER PROJEKTSTRUKTUR ---
echo -e "\n\n${BLUE}======================================================="
echo "                 Aktuelle Projektstruktur"
echo -e "=======================================================${NC}"

# Einfache Strukturansicht
list_structure() {
    find "$PROJECT_ROOT" -maxdepth 3 -path "$PROJECT_ROOT/.venv" -prune -o \
                         -path "$PROJECT_ROOT/logs" -prune -o \
                         -path "$PROJECT_ROOT/.git" -prune -o \
                         -path '*/__pycache__' -prune -o \
                         -print | sed -e "s;$PROJECT_ROOT;.;" -e 's;[^/]*/;|____;g;s;____|; |;g'
}

list_structure

echo -e "${BLUE}=======================================================${NC}"
