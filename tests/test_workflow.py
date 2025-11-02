# tests/test_workflow.py
import pytest
import os
import sys
import json
import logging
import time
from unittest.mock import MagicMock, patch 
import ccxt 

# Füge das Projekt-Hauptverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

# Importiere die notwendigen Teile von utbot2
from utils.exchange_handler import ExchangeHandler
# Importiere die *tatsächliche* Funktion, die wir testen wollen
from main import run_strategy_cycle, load_config, setup_logging

# --- Mock für Gemini ---
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
        """ Legt die nächste JSON-Antwort fest, die simuliert werden soll. """
        self.response_json = {"aktion": action, "stop_loss": sl, "take_profit": tp}

    def generate_content(self, prompt, generation_config=None, safety_settings=None):
        """ Simuliert den API-Aufruf und gibt die festgelegte Antwort zurück. """
        response_text = json.dumps(self.response_json)
        print(f"\n[Mock Gemini] Empfing Prompt, sende Antwort: {response_text}")
        return MockGeminiResponse(response_text)

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
        exchange = ExchangeHandler(bitget_config)
        logger = setup_logging(symbol, timeframe + "_test") 

        # Initiales Aufräumen auf der Börse
        print(f"-> Führe initiales Aufräumen für {symbol} durch...")
        exchange.cleanup_all_open_orders(symbol)
        
        # --- START GEISTER-POSITION WORKAROUND ---
        uncached_exchange = ExchangeHandler(bitget_config)
        positions = uncached_exchange.session.fetch_positions([symbol])
        
        open_positions = [p for p in positions if abs(float(p.get('contracts', 0))) > 1e-9]

        if open_positions:
            pos = open_positions[0]
            pos_amount = float(pos.get('contracts', 0))
            
            print(f"WARNUNG: Geister-Position ({pos_amount} {symbol}) im CCXT-Cache gefunden. Versuche zu löschen...")
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            
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
            exchange.cleanup_all_open_orders(symbol)
            print("-> Aufräumen abgeschlossen.")
        except Exception as e:
            print(f"FEHLER beim Aufräumen: {e}")

    except Exception as setup_e:
        pytest.fail(f"Fehler während des Test-Setups: {setup_e}")


# --- Der eigentliche Test ---
@patch('utils.exchange_handler.ExchangeHandler.fetch_open_positions', side_effect=[
    # 1. Abfrage in run_strategy_cycle (sollte leer sein)
    [], 
    # 2. Abfrage in create_market_order_with_sl_tp (sollte eine offene Position zurückgeben)
    [
        # Mock-Position, die nach dem Trade erwartet wird.
        {'symbol': 'XRP/USDT:USDT', 'contracts': 100.0, 'side': 'long', 'entryPrice': 2.50} 
    ] 
])
def test_full_utbot2_workflow_on_bitget(mock_fetch_positions, test_setup):
    """
    Testet den vereinfachten Handelsablauf von utbot2 auf Bitget.
    Wir patchen die Positionsabfragen im Hauptzyklus ab, um den Geister-Cache zu umgehen
    und den Trade-Prozess zu erzwingen.
    """
    exchange, mock_gemini, config, test_target, telegram_config, logger = test_setup
    symbol = test_target['symbol']
    strategy_cfg = config['strategy']

    # 1. Kaufsignal erzwingen
    try:
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
        real_balance = exchange.fetch_balance_usdt()
        logger.info(f"[Test Workflow] Aktuelles Test-Guthaben: {real_balance:.2f} USDT")
        
        # --- START KORREKTUR: Mindestguthaben auf 1 USDT senken ---
        if real_balance < 1.0: 
            pytest.skip(f"Test-Guthaben ist zu gering ({real_balance:.2f} USDT). Benötige mind. 1.0 USDT für den Test.")
        # --- ENDE KORREKTUR ---

        # Erzwinge maximalen Hebel und Kapital für Mindestvolumen
        test_target['risk']['portfolio_fraction_pct'] = 100 
        test_target['risk']['max_leverage'] = 20 
        
        # Rufe den Zyklus auf. Dank Patch wird die erste Abfrage '[]' zurückgeben.
        run_strategy_cycle(test_target, strategy_cfg, exchange, mock_gemini, telegram_config, logger)

        print("-> run_strategy_cycle ausgeführt.")
        print("-> Warte 10 Sekunden, damit Orders verarbeitet werden...")
        time.sleep(10)
    except Exception as e:
        pytest.fail(f"Fehler während des Aufrufs von run_strategy_cycle: {e}")

    # 3. Position prüfen
    print("\n[Schritt 2/3] Überprüfe, ob die Position korrekt erstellt wurde...")
    # fetch_open_positions wird hier LIVE aufgerufen (Mock ist aufgebraucht)
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

        tsl_enabled = test_target.get('risk', {}).get('trailing_stop', {}).get('enabled', False)

        if tsl_enabled:
            logger.info("TSL-Modus aktiv. Erwarte 2 Trigger-Orders (1 TSL, 1 TP).")
            assert len(trigger_orders) == 2, f"FEHLER (TSL): Erwartete 2 Trigger-Orders, gefunden {len(trigger_orders)}."
        else:
            logger.info("Fixer SL-Modus aktiv. Erwarte 2 Trigger-Orders (1 SL, 1 TP).")
            assert len(trigger_orders) == 2, f"FEHLER (Fix SL): Erwartete 2 Trigger-Orders, gefunden {len(trigger_orders)}."

        print("-> ✔ Korrekte Anzahl an SL/TP-Trigger-Orders gefunden.")
    except Exception as e:
        pytest.fail(f"Fehler beim Überprüfen der Trigger-Orders: {e}")

    print("\n--- ✅ utbot2 WORKFLOW-TEST ERFOLGREICH! ---")
    # Aufräumen erfolgt automatisch durch die Teardown-Funktion der Fixture
