# utbot2/master_runner.py (Inspiriert von JaegerBot)
import json
import subprocess
import sys
import os
import time
import toml # Hinzugefügt für config.toml

# --- Konfiguration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR # Annahme: master_runner.py liegt im Hauptverzeichnis
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'config.toml') # Angepasst an .toml
BOT_RUNNER_SCRIPT = os.path.join(PROJECT_ROOT, 'main.py') # Pfad zur überarbeiteten main.py
VENV_PYTHON = os.path.join(PROJECT_ROOT, '.venv', 'bin', 'python3')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
MASTER_LOG_FILE = os.path.join(LOG_DIR, 'master_runner.log')

# --- Einfaches Logging für den Master ---
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s UTC - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    handlers=[
                        logging.FileHandler(MASTER_LOG_FILE, mode='a', encoding='utf-8'),
                        logging.StreamHandler() # Auch auf Konsole ausgeben
                    ])
logging.Formatter.converter = time.gmtime
logger = logging.getLogger('MasterRunner')

# --- Hilfsfunktion zum Laden (angepasst für toml) ---
def load_toml_config(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except FileNotFoundError:
        logger.critical(f"FATAL: Konfigurationsdatei nicht gefunden: {file_path}")
        return None
    except Exception as e:
        logger.critical(f"FATAL: Fehler beim Laden der TOML-Konfigurationsdatei {file_path}: {e}")
        return None

def main():
    logger.info("=======================================================")
    logger.info("utbot2 Master Runner v1.0 (Cron Job)")
    logger.info("=======================================================")

    # --- Prüfe venv ---
    if not os.path.exists(VENV_PYTHON):
        logger.critical(f"Fehler: Python-Interpreter in der venv nicht gefunden: {VENV_PYTHON}")
        logger.critical("Bitte 'install.sh' ausführen.")
        return

    # --- Lade Konfiguration ---
    config = load_toml_config(SETTINGS_FILE)
    if not config:
        return

    # --- Finde aktive Targets ---
    active_targets = []
    try:
        for target in config.get('targets', []):
            if target.get('enabled', False):
                if 'symbol' in target and 'timeframe' in target:
                    active_targets.append(target)
                else:
                    logger.warning(f"Überspringe unvollständiges Target in config.toml: {target}")
    except Exception as e:
        logger.error(f"Fehler beim Verarbeiten der Targets aus config.toml: {e}")
        return

    if not active_targets:
        logger.info("Keine aktiven Targets in config.toml gefunden. Beende diesen Lauf.")
        return

    logger.info(f"Gefundene aktive Targets: {len(active_targets)}")
    logger.info("=======================================================")

    # --- Starte Subprozesse für jedes Target ---
    processes = []
    for target in active_targets:
        symbol = target['symbol']
        timeframe = target['timeframe']

        logger.info(f"--- Starte Bot für: {symbol} ({timeframe}) ---")

        command = [
            VENV_PYTHON,          # Python aus der venv
            BOT_RUNNER_SCRIPT,    # Das main.py Skript
            "--symbol", symbol,
            "--timeframe", timeframe
        ]

        try:
            # Starte den Prozess im Hintergrund
            # stdout/stderr werden in die jeweiligen Strategie-Logs geschrieben (durch main.py's setup_logging)
            process = subprocess.Popen(command)
            processes.append(process)
            logger.info(f"-> Prozess für {symbol} ({timeframe}) gestartet (PID: {process.pid}).")
            # Kurze Pause, um Rate Limits beim Start zu vermeiden
            time.sleep(5) # 5 Sekunden Pause zwischen Starts
        except Exception as e:
            logger.error(f"FEHLER beim Starten des Prozesses für {symbol} ({timeframe}): {e}", exc_info=True)

    # Optional: Auf Beendigung der Prozesse warten (eher untypisch für Cron-Jobs)
    # logger.info("Alle Prozesse gestartet. Master Runner beendet sich.")
    # for p in processes:
    #     p.wait() # Wartet bis der jeweilige main.py Prozess fertig ist
    # logger.info("Alle Subprozesse beendet.")

if __name__ == "__main__":
    main()
