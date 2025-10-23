# tests/test_basic.py
import os
import sys
import pytest

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

def test_imports():
    """ Prüft, ob die wichtigsten Module importiert werden können. """
    try:
        from utils.exchange_handler import ExchangeHandler
        from utils.guardian import guardian_decorator
        from utils.telegram_handler import send_telegram_message
        import main # Versucht, die Hauptdatei zu importieren
        print("\nGrundlegende Modul-Imports erfolgreich.")
    except ImportError as e:
        pytest.fail(f"Kritischer Import-Fehler. Struktur defekt? Fehler: {e}")

def test_config_loading():
    """ Prüft, ob die config.toml geladen werden kann. """
    try:
        from main import load_config # Importiere die Ladefunktion
        config = load_config('config.toml')
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
