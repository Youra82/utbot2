# tests/test_basic.py
import os
import sys
import pytest
import json # Wichtig für json.load
import toml # Wichtig für toml.load
from pathlib import Path # Wichtig für saubere Pfade

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, str(PROJECT_ROOT))


# --- HELFER FUNKTION (Wiederherstellung von load_config) ---
def local_load_config(file_path):
    """Lokaler Ersatz für die gelöschte load_config-Funktion."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    if p.suffix == '.toml': 
        # toml.load(Path) ist fehlerhaft, öffnen mit 'r' ist sicherer
        with open(p, 'r', encoding='utf-8') as f:
            return toml.load(f)
    elif p.suffix == '.json': 
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    raise ValueError("Unknown config format")
# --- ENDE HELPER ---


def test_imports():
    """ Prüft, ob die wichtigsten Module importiert werden können. """
    try:
        # Versuchen wir, die Module direkt zu importieren, anstatt uns auf main.py zu verlassen
        from utils.exchange_handler import ExchangeHandler
        from utils.telegram_handler import send_telegram_message
        import main 
        print("\nGrundlegende Modul-Imports erfolgreich.")
    except ImportError as e:
        pytest.fail(f"Kritischer Import-Fehler. Struktur defekt? Fehler: {e}")


def test_config_loading():
    """ Prüft, ob die config.toml geladen werden kann. """
    try:
        # Nutze die lokale Helper-Funktion
        config = local_load_config(PROJECT_ROOT / 'config.toml')
        assert isinstance(config, dict)
        assert 'strategy' in config
        assert 'targets' in config
        print("\nconfig.toml erfolgreich geladen und grundlegend validiert.")
    except Exception as e:
        pytest.fail(f"Fehler beim Laden oder Validieren der config.toml: {e}")

# Hier könntest du weitere Tests hinzufügen, z.B.:
# - Teste ExchangeHandler-Funktionen (mit Mocking oder Test-Account)
# - Teste Prompt-Erstellung
# - Teste Risikoberechnung
