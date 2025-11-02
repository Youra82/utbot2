# tests/test_workflow.py (KORRIGIERT - vollständige Datei)
import pytest
import os
import sys
import json
import logging
import time
from pathlib import Path
import ccxt
import pandas as pd
from unittest.mock import patch, MagicMock

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))
sys.path.append(PROJECT_ROOT)

from utils.exchange_handler import ExchangeHandler
from main import run_strategy_cycle

# --- HELPER FUNKTIONEN ---
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


# --- Mock Klassen (NUR FÜR GEMINI) ---
class MockGeminiResponse:
    def __init__(self, text_content):
        self.text = text_content
        self.parts = [True] if text_content else []

class MockGeminiModel:
    """Mock Gemini API Response für Trade-Signal"""
    def __init__(self):
        self.response_json = {"aktion": "KAUFEN", "stop_loss": 0, "take_profit": 0}

    def set_next_response(self, action="KAUFEN", sl=None, tp=None):
        self.response_json = {"aktion": action, "stop_loss": sl or 2.4500, "take_profit": tp or 2.6000}

    def generate_content(self, prompt, generation_config=None, safety_settings=None):
        current_price = 2.50 # Fallback

        if prompt and "aktueller_preis" in str(prompt):
            try:
                # robustes Parsen falls prompt-Format leicht variiert
                p = str(prompt)
                if "aktueller_preis=" in p:
                    current_price = float(p.split("aktueller_preis=")[1].split(",")[0].strip().strip("'\""))
            except:
                pass

        mock_sl = current_price * 0.98
        mock_tp = current_price * 1.04

        self.set_next_response(sl=mock_sl, tp=mock_tp)
        response_text = json.dumps(self.response_json)
        print(f"\n[Mock Gemini] Empfing Prompt, sende Antwort: {response_text}")
        return MockGeminiResponse(response_text)


# --- Test Setup (Fixture) ---
# Mock fetch_ohlcv, da der Test sonst 1440 Kerzen laden müsste
@patch('utils.exchange_handler.ExchangeHandler.fetch_ohlcv', MagicMock(return_value=pd.DataFrame(
    # Genug Kerzen, um die 60er-Prüfung zu bestehen
    {'open': 2.4, 'high': 2.6, 'low': 2.3, 'close': 2.5, 'volume': 1000},
    index=pd.to_datetime(pd.RangeIndex(start=1, stop=101), unit='s', utc=True)
).iloc[:100]))
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

        exchange = ExchangeHandler()
        logger = setup_logging(symbol, timeframe + "_test")

        # Session Initialisierung (Live-Code)
        exchange.session = ccxt.bitget({
            'apiKey': bitget_config['apiKey'],
            'secret': bitget_config['secret'],
            'password': bitget_config['password'],
            'options': {'defaultType': 'swap'},
        })
        exchange.session.load_markets()

        # --- SICHERHEITS-CHECK VOR DEM TEST (Geister-Positionen löschen) ---
        print(f"-> Führe initiales Aufräumen für {symbol} durch...")
        try:
            exchange.cleanup_all_open_orders(symbol)
        except Exception as e_cleanup:
            print(f"INFO: cleanup_all_open_orders schlug fehl: {e_cleanup}")

        positions = exchange.fetch_open_positions(symbol)
        if positions:
            pos = positions[0]
            pos_amount = float(pos.get('contracts', 0))

            print(f"WARNUNG: Geister-Position ({pos_amount} {symbol}) gefunden. Versuche zu schließen...")
            close_side = 'sell' if pos['side'] == 'long' else 'buy'

            try:
                exchange.create_market_order(symbol, close_side, pos_amount, params={'reduceOnly': True})
                time.sleep(2)
                if exchange.fetch_open_positions(symbol):
                    pytest.fail(f"KRITISCH: Konnte Geisterposition für {symbol} nicht schließen.")
            except Exception as e:
                print(f"INFO: Harter Schließversuch fehlgeschlagen, nehme an Position ist weg. Fehler: {e}")
        # --- ENDE SICHERHEITS-CHECK ---

        print("-> Ausgangszustand ist sauber.")

        mock_gemini = MockGeminiModel()
        yield exchange, mock_gemini, config, test_target, telegram_config, logger

        # --- Teardown ---
        print("\n--- [Teardown] Räume nach dem Test auf... ---")
        try:
            exchange.cleanup_all_open_orders(symbol)
            print("-> Aufräumen abgeschlossen.")
        except Exception as e:
            print(f"FEHLER beim Aufräumen: {e}")

    except Exception as setup_e:
        pytest.fail(f"Fehler während des Test-Setups: {setup_e}")


def test_full_utbot2_workflow_on_bitget(test_setup):
    """
    Testet den vereinfachten Handelsablauf von utbot2 auf Bitget (Live-Trade).
    """
    exchange, mock_gemini, config, test_target, telegram_config, logger = test_setup
    symbol = test_target['symbol']
    strategy_cfg = config['strategy']

    # 1. Kaufsignal erzwingen
    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        mock_gemini.set_next_response(action="KAUFEN", sl=current_price * 0.98, tp=current_price * 1.04)
        print(f"\n[Schritt 1/3] Mock Gemini wird 'KAUFEN' signalisieren (Preis={current_price:.4f}, SL={current_price * 0.98:.4f}, TP={current_price * 1.04:.4f}).")
    except Exception as e:
        pytest.fail(f"Konnte Ticker nicht abrufen, um Mock-Antwort vorzubereiten: {e}")

    # 2. Hauptzyklus aufrufen (LIVE-TRADE!)
    print("[Schritt 1/3] Rufe run_strategy_cycle auf...")
    try:
        real_balance = exchange.fetch_balance_usdt()
        logger.info(f"[Test Workflow] Aktuelles Test-Guthaben: {real_balance:.2f} USDT")

        if real_balance < 1.0:
            pytest.skip(f"Test-Guthaben ist zu gering ({real_balance:.2f} USDT). Benötige mind. 1.0 USDT für den Test.")

        test_target['risk']['portfolio_fraction_pct'] = 100
        test_target['risk']['max_leverage'] = 100

        run_strategy_cycle(test_target, strategy_cfg, exchange, mock_gemini, telegram_config, logger)

        print("-> run_strategy_cycle ausgeführt.")
        print("-> Warte 10 Sekunden, damit Orders verarbeitet werden...")
        time.sleep(10)
    except Exception as e:
        pytest.fail(f"Fehler während des Aufrufs von run_strategy_cycle: {e}")

    # 3. Position prüfen
    print("\n[Schritt 2/3] Überprüfe, ob die Position korrekt erstellt wurde...")
    try:
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
        trigger_orders = exchange.fetch_open_trigger_orders(symbol)

        # SL + TP = 2 Orders
        assert len(trigger_orders) == 2, f"FEHLER: Erwartete 2 Trigger Orders, gefunden {len(trigger_orders)}."

        print("-> ✔ Korrekte Anzahl an SL/TP-Trigger-Orders gefunden.")
    except Exception as e:
        pytest.fail(f"Fehler beim Überprüfen der Trigger-Orders: {e}")

    print("\n--- ✅ utbot2 WORKFLOW-TEST ERFOLGREICH! ---")
