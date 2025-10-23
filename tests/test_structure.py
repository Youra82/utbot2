# tests/test_structure.py
import os
import sys
import pytest

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

def test_project_structure():
    """Stellt sicher, dass alle erwarteten Hauptverzeichnisse/Dateien existieren."""
    assert os.path.isdir(os.path.join(PROJECT_ROOT, 'utils')), "Das 'utils'-Verzeichnis fehlt."
    assert os.path.isdir(os.path.join(PROJECT_ROOT, 'tests')), "Das 'tests'-Verzeichnis fehlt."
    assert os.path.isfile(os.path.join(PROJECT_ROOT, 'main.py')), "Die 'main.py'-Datei fehlt."
    assert os.path.isfile(os.path.join(PROJECT_ROOT, 'config.toml')), "Die 'config.toml'-Datei fehlt."
    assert os.path.isfile(os.path.join(PROJECT_ROOT, 'requirements.txt')), "Die 'requirements.txt'-Datei fehlt."

def test_core_script_imports():
    """
    Stellt sicher, dass die wichtigsten Funktionen/Klassen importiert werden können.
    Dies ist ein schneller Check, ob die grundlegende Code-Struktur intakt ist.
    """
    try:
        from main import main as main_function, attempt_new_trade # Hauptfunktionen
        from utils.exchange_handler import ExchangeHandler, ExchangeHandler # Importiere die Klasse
        from utils.guardian import guardian_decorator
        from utils.telegram_handler import send_telegram_message
        # Teste, ob Hauptmodule selbst importierbar sind
        import utils.exchange_handler
        import utils.guardian
        import utils.telegram_handler
    except ImportError as e:
        pytest.fail(f"Kritischer Import-Fehler. Struktur defekt? Fehler: {e}")
    except Exception as e:
         pytest.fail(f"Anderer Fehler beim Importieren: {e}")
