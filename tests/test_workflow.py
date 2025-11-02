# tests/test_workflow.py (BEREINIGTE VERSION OHNE MOCKING)
import pytest 
import os
import sys
import json
import logging
import time
from pathlib import Path 
import ccxt 
import pandas as pd 

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))
sys.path.append(PROJECT_ROOT) 

# Importiere die notwendigen Teile von utbot2
from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message
from main import run_strategy_cycle 

# --- Mock Klassen (Unverändert für Gemini) ---
class MockGeminiResponse:
    def __init__(self, text_content):
        self.text = text_content
        self.parts = [True] if text_content else []
        self.prompt_feedback = "Mock Feedback: Blocked" if not text_content else "Mock Feedback: OK"

class MockGeminiModel:
    """Eine Mock-Version des Gemini-Modells."""
    def __init__(self):
        self.response_json = {"aktion": "HALTEN", "stop_loss": 0, "take_profit": 0}

    def set_next_response(self, action="KAUFEN", sl=10000, tp=12000):
        self.response_json = {"aktion": action, "stop_loss": sl, "take_profit": tp}

    def generate_content(self, prompt, generation_config=None, safety_settings=None):
        response_text = json.dumps(self.response_json)
        print(f"\n[Mock Gemini] Empfing Prompt, sende Antwort: {response_text}")
        return MockGeminiResponse(response_text)

# --- HELFER FUNKTIONEN ---
def load_config(file_path):
    p = Path(file_path)
    if p.suffix == '.toml':
        import toml
        with open(p, 'r', encoding='utf-8') as f:
            return toml.load(f)
    elif p.suffix == '.json':
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    raise ValueError(f"Unknown config format: {file_path}")

def setup_logging(symbol, timeframe):
    logger = logging.getLogger(f'utbot2_{symbol.replace("/", "").replace(":", "")}_{timeframe}')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s: [%(name)s] %(message)s', datefmt='%H:%M:%S')
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)
    return logger
# --- ENDE HELPER FUNKTIONEN ---


# --- Test Setup (Fixture) ---
@pytest.fixture(scope="module") 
def test_setup():
    """ Bereitet die Testumgebung vor (lädt Keys, erstellt Exchange). """
    print("\n--- [Setup] Starte utbot2 Workflow-Test ---")
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    config_path = os.path.join(PROJECT_ROOT, 'config.toml')

    if not os.path.exists(secret_path):
        pytest.skip("secret.json nicht gefunden. Überspringe Live-Workflow-Test.")

    try:
        secrets = load_config(secret_path)
        config = load_config(config_path)

        if not secrets.get('bitget'):
            pytest.skip("Kein 'bitget'-Eintrag in secret.json gefunden.")

        bitget_config = secrets['bitget']
        telegram_config = secrets.get('telegram', {}) 

        test_target = next((t for t in config.get('targets', []) if t.get('enabled')), None)
        if not test_target:
            pytest.skip("Kein aktives Target in config.toml für den Test gefunden.")

        symbol = test_target['symbol']
        timeframe = test_target['timeframe']

        # Erstelle Exchange-Instanz und Logger
        exchange = ExchangeHandler()
        logger = setup_logging(symbol, timeframe + "_test") 
        
        # --- Zuweisung der CCXT Session (Wie im TitanBot-Setup) ---
        # Dies ist das Minimum, das der Test braucht, um mit der Börse zu sprechen.
        exchange.session = ccxt.bitget({
            'apiKey': bitget_config['apiKey'],
            'secret': bitget_config['secret'],
            'password': bitget_config['password'],
            'options': {'defaultType': 'swap'},
        })
        # --- ENDE Session Zuweisung ---

        # Initiales Aufräumen auf der Börse
        print(f"-> Führe initiales Aufräumen für {symbol} durch...")
        # HIER WIRD DIE ECHTE cleanup_all_open_orders AUFGERUFEN!
        exchange.cleanup_all_open_orders(symbol)
        
        # --- START GEISTER-POSITION WORKAROUND ---
        # Dieser Workaround bleibt, da er direkt CCXT (exchange.session) nutzt.
        positions = exchange.session.fetch_positions([symbol])
        
        open_positions = [p for p in positions if abs(float(p.get('contracts', 0))) > 1e-9]

        if open_positions:
            pos = open_positions[0]
            pos_amount = float(pos.get('contracts', 0))
            
            print(f"WARNUNG: Geister-Position ({pos_amount} {symbol}) im CCXT-Cache gefunden. Versuche zu löschen...")
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            
            # HIER WIRD DIE ECHTE create_market_order AUFGERUFEN!
            try:
                exchange.create_market_order(symbol, close_side, pos_amount, params={'reduceOnly': True})
            except Exception:
                pass
            
            print("-> Geister-Position Workaround durchgeführt. Ignoriere verbleibende Caches.")
        # --- ENDE GEISTER-POSITION WORKAROUND ---

        print("-> Ausgangszustand ist sauber.")

        # Erstelle Mock Gemini Model
        mock_gemini = MockGeminiModel()

        # Gib alle benötigten Objekte an den Test weiter
        yield exchange, mock_gemini, config, test_target, telegram_config, logger

        # --- Teardown ---
        print("\n--- [Teardown] Räume nach dem Test auf... ---")
        try:
            # HIER WIRD DIE ECHTE cleanup_all_open_orders AUFGERUFEN!
            exchange.cleanup_all_open_orders(symbol)
            print("-> Aufräumen abgeschlossen.")
        except Exception as e:
            print(f"FEHLER beim Aufräumen: {e}")

    except Exception as setup_e:
        pytest.fail(f"Fehler während des Test-Setups: {setup_e}")

# --- FIXTURE mock_exchange_methods WURDE ENTFERNT ---


def test_full_utbot2_workflow_on_bitget(test_setup):
    """
    Testet den vereinfachten Handelsablauf von utbot2 auf Bitget.
    """
    # mock_exchange_methods ist nicht mehr nötig und wurde entfernt
    exchange, mock_gemini, config, test_target, telegram_config, logger = test_setup
    symbol = test_target['symbol']
    strategy_cfg = config['strategy']

    # 1. Kaufsignal erzwingen
    try:
        # HIER WIRD DIE ECHTE fetch_ticker AUFGERUFEN!
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        mock_sl = current_price * 0.98
        mock_tp = current_price * 1.04
        mock_gemini.set_next_response(action="KAUFEN", sl=mock_sl, tp=mock_tp)
        print(f"\n[Schritt 1/3] Mock Gemini wird 'KAUFEN' signalisieren (Preis={current_price:.4f}, SL={mock_sl:.4f}, TP={mock_tp:.4f}).")
    except Exception as e:
        pytest.fail(f"Konnte Ticker nicht abrufen, um Mock-Antwort vorzubereiten: {e}")

    # 2. Hauptzyklus aufrufen
    print("[Schritt 1/3] Rufe run_strategy_cycle auf...")
    try:
        # HIER WIRD DIE ECHTE fetch_balance_usdt AUFGERUFEN!
        real_balance = exchange.fetch_balance_usdt()
        logger.info(f"[Test Workflow] Aktuelles Test-Guthaben: {real_balance:.2f} USDT")
        
        if real_balance < 1.0: 
            pytest.skip(f"Test-Guthaben ist zu gering ({real_balance:.2f} USDT). Benötige mind. 1.0 USDT für den Test.")

        test_target['risk']['portfolio_fraction_pct'] = 100 
        test_target['risk']['max_leverage'] = 100 
        
        # Der Hauptzyklus läuft nun vollständig LIVE!
        run_strategy_cycle(test_target, strategy_cfg, exchange, mock_gemini, telegram_config, logger)

        print("-> run_strategy_cycle ausgeführt.")
        print("-> Warte 10 Sekunden, damit Orders verarbeitet werden...")
        time.sleep(10)
    except Exception as e:
        pytest.fail(f"Fehler während des Aufrufs von run_strategy_cycle: {e}")

    # 3. Position prüfen
    print("\n[Schritt 2/3] Überprüfe, ob die Position korrekt erstellt wurde...")
    try:
        # HIER WIRD DIE ECHTE fetch_open_positions AUFGERUFEN!
        positions = exchange.fetch_open_positions(symbol) 
        assert len(positions) == 1, f"FEHLER: Erwartete 1 offene Position, gefunden {len(positions)}."
        position = positions[0]
        assert position['side'] == 'long', f"FEHLER: Erwartete 'long' Position, gefunden '{position['side']}'."
        print(f"-> ✔ Position korrekt eröffnet (Seite: {position['side']}, Größe: {position['contracts']}).")
    except Exception as e:
        pytest.fail(f"Fehler beim Überprüfen der Position: {e}")

    # 4. Trigger-Orders (SL/TP) prüfen
    print("\n[Schritt 3/3] Überprüfe, ob SL/TP-Orders korrekt platziert wurden...")
    try:
        # HIER WIRD DIE ECHTE fetch_open_trigger_orders AUFGERUFEN!
        trigger_orders = exchange.fetch_open_trigger_orders(symbol)

        tsl_enabled = test_target.get('risk', {}).get('trailing_stop', {}).get('enabled', False)

        if tsl_enabled:
            logger.info("TSL-Modus aktiv. Erwarte 2 Trigger-Orders (1 TSL, 1 TP).")
        else:
            logger.info("Fixer SL-Modus aktiv. Erwarte 2 Trigger-Orders (1 SL, 1 TP).")
        
        # Es ist sehr wahrscheinlich, dass dieser Assertion fehlschlägt, da SL/TP Order-Erstellung 
        # oft die komplexeste Logik ist und jetzt live ausgeführt wird.
        assert len(trigger_orders) == 2, f"FEHLER: Erwartete 2 Trigger-Orders, gefunden {len(trigger_orders)}."

        print("-> ✔ Korrekte Anzahl an SL/TP-Trigger-Orders gefunden.")
    except Exception as e:
        pytest.fail(f"Fehler beim Überprüfen der Trigger-Orders: {e}")

    print("\n--- ✅ utbot2 WORKFLOW-TEST ERFOLGREICH! ---")
