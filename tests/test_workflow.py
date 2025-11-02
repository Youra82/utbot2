# tests/test_workflow.py
import pytest
import os
import sys
import json
import logging
import time
from unittest.mock import MagicMock # Zum Mocken von Gemini

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
        # Simuliere die 'parts'-Struktur, wenn sie im Code geprüft wird
        self.parts = [True] if text_content else []
        # Simuliere 'prompt_feedback' für den Fehlerfall
        self.prompt_feedback = "Mock Feedback: Blocked" if not text_content else "Mock Feedback: OK"

class MockGeminiModel:
    """Eine Mock-Version des Gemini-Modells."""
    def __init__(self):
        # Standardmäßig "HALTEN" zurückgeben
        self.response_json = {"aktion": "HALTEN", "stop_loss": 0, "take_profit": 0}

    def set_next_response(self, action="KAUFEN", sl=10000, tp=12000):
        """ Legt die nächste JSON-Antwort fest, die simuliert werden soll. """
        self.response_json = {"aktion": action, "stop_loss": sl, "take_profit": tp}

    def generate_content(self, prompt, generation_config=None, safety_settings=None):
        """ Simuliert den API-Aufruf und gibt die festgelegte Antwort zurück. """
        # Wichtig: Formatiere die Antwort so, wie Gemini es tun würde (ggf. mit ```json)
        # Hier geben wir direkt sauberes JSON zurück, wie es nach dem cleanen wäre.
        response_text = json.dumps(self.response_json)
        print(f"\n[Mock Gemini] Empfing Prompt, sende Antwort: {response_text}")
        return MockGeminiResponse(response_text)

# --- Test Setup (Fixture) ---
@pytest.fixture(scope="module") # scope="module", damit Setup nur einmal pro Datei läuft
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

        # Verwende den ersten Bitget-Account aus der Liste
        if not secrets.get('bitget'):
            pytest.skip("Kein 'bitget'-Eintrag in secret.json gefunden.")

        bitget_config = secrets['bitget']
        telegram_config = secrets.get('telegram', {}) # Optional

        # Wähle ein Target aus der config.toml für den Test
        # Nehme das erste aktive Target
        test_target = next((t for t in config.get('targets', []) if t.get('enabled')), None)
        if not test_target:
            pytest.skip("Kein aktives Target in config.toml für den Test gefunden.")

        symbol = test_target['symbol']
        timeframe = test_target['timeframe']

        # Erstelle Exchange-Instanz und Logger
        exchange = ExchangeHandler(bitget_config)
        logger = setup_logging(symbol, timeframe + "_test") # Eigener Logger für Tests

        # Initiales Aufräumen auf der Börse
        print(f"-> Führe initiales Aufräumen für {symbol} durch...")
        exchange.cleanup_all_open_orders(symbol)
        positions = exchange.fetch_open_positions(symbol)
        if positions:
            print(f"WARNUNG: Offene Position für {symbol} gefunden. Versuche Not-Schließung...")
            pos = positions[0]
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            try:
                # Nutze 'reduceOnly' um sicherzustellen, dass wir nur schließen
                exchange.create_market_order(symbol, close_side, float(pos['contracts']), params={'reduceOnly': True, 'posSide': 'net', 'tradeSide': 'close'})
                time.sleep(3) # Warte auf Schließung
            except Exception as e_close:
                pytest.fail(f"Konnte initiale Position nicht schließen: {e_close}")
        print("-> Ausgangszustand ist sauber.")

        # Erstelle Mock Gemini Model
        mock_gemini = MockGeminiModel()

        # Gib alle benötigten Objekte an den Test weiter
        yield exchange, mock_gemini, config, test_target, telegram_config, logger

        # --- Teardown ---
        print("\n--- [Teardown] Räume nach dem Test auf... ---")
        try:
            exchange.cleanup_all_open_orders(symbol)
            positions = exchange.fetch_open_positions(symbol)
            if positions:
                print("WARNUNG: Position nach Test noch offen. Versuche Not-Schließung.")
                pos = positions[0]
                close_side = 'sell' if pos['side'] == 'long' else 'buy'
                # --- KORREKTUR: 'tradeSide': 'close' hinzugefügt für Konsistenz ---
                exchange.create_market_order(symbol, close_side, float(pos['contracts']), params={'reduceOnly': True, 'posSide': 'net', 'tradeSide': 'close'})
            print("-> Aufräumen abgeschlossen.")
        except Exception as e:
            print(f"FEHLER beim Aufräumen: {e}")

    except Exception as setup_e:
        pytest.fail(f"Fehler während des Test-Setups: {setup_e}")


# --- Der eigentliche Test ---
def test_full_utbot2_workflow_on_bitget(test_setup):
    """
    Testet den vereinfachten Handelsablauf von utbot2 auf Bitget:
    1. Erzwingt ein Kaufsignal über das Mock-Gemini-Modell.
    2. Ruft die Hauptzyklusfunktion `run_strategy_cycle` auf.
    3. Prüft, ob eine Position eröffnet wurde.
    4. Prüft, ob SL- und TP-Trigger-Orders platziert wurden.
    (Das Teardown der Fixture räumt danach auf.)
    """
    exchange, mock_gemini, config, test_target, telegram_config, logger = test_setup
    symbol = test_target['symbol']
    strategy_cfg = config['strategy']

    # 1. Kaufsignal erzwingen
    # Hole aktuellen Preis, um plausible SL/TP zu setzen
    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        # Setze SL 2% unter Preis, TP 4% über Preis (Beispiel)
        mock_sl = current_price * 0.98
        mock_tp = current_price * 1.04
        mock_gemini.set_next_response(action="KAUFEN", sl=mock_sl, tp=mock_tp)
        print(f"\n[Schritt 1/3] Mock Gemini wird 'KAUFEN' signalisieren (Preis={current_price:.4f}, SL={mock_sl:.4f}, TP={mock_tp:.4f}).")
    except Exception as e:
        pytest.fail(f"Konnte Ticker nicht abrufen, um Mock-Antwort vorzubereiten: {e}")

    # 2. Hauptzyklus aufrufen
    print("[Schritt 1/3] Rufe run_strategy_cycle auf...")
    try:
        
        # -----------------------------------------------------------------
        # --- START DER KORREKTUR (TitanBot-Stil) ---
        # -----------------------------------------------------------------
        # 1. Wir verwenden KEIN dummy_balance mehr.
        # 2. Wir holen das ECHTE Guthaben, um sicherzustellen, dass der Test laufen KANN.
        
        try:
            real_balance = exchange.fetch_balance_usdt()
            logger.info(f"[Test Workflow] Aktuelles Test-Guthaben: {real_balance:.2f} USDT")
            if real_balance < 10: # Mindestguthaben für einen Trade
                pytest.skip(f"Test-Guthaben ist zu gering ({real_balance:.2f} USDT). Benötige mind. 10 USDT für den Test.")
        except Exception as e:
            pytest.fail(f"Konnte reales Guthaben für den Test nicht abrufen: {e}")

        # 3. Wir setzen die portfolio_fraction_pct zurück auf den Wert aus der config,
        #    da der 1%-Puffer jetzt in main.py eingebaut ist.
        #    (Finde das erste Target in der config, das dem Test-Target entspricht)
        original_target_config = next((t for t in config.get('targets', []) if t.get('symbol') == symbol), None)
        if original_target_config:
             test_target['risk']['portfolio_fraction_pct'] = original_target_config['risk']['portfolio_fraction_pct']
        else:
             logger.warning("Konnte Original-Config nicht finden, fahre mit potenziell altem Wert fort.")


        # 4. Rufe den Zyklus OHNE balance-Argument auf.
        run_strategy_cycle(test_target, strategy_cfg, exchange, mock_gemini, telegram_config, logger)
        
        # -----------------------------------------------------------------
        # --- ENDE DER KORREKTUR ---
        # -----------------------------------------------------------------
        
        print("-> run_strategy_cycle ausgeführt.")
        # Wartezeit, damit Orders bei Bitget verarbeitet werden können
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
        
        # Wir prüfen, ob TSL in der Config aktiviert ist
        tsl_enabled = test_target.get('risk', {}).get('trailing_stop', {}).get('enabled', False)
        
        if tsl_enabled:
            # Wenn TSL aktiv ist, erwarten wir 1 TSL-Order (die SL) und 1 TP-Order
            logger.info("TSL-Modus aktiv. Erwarte 2 Trigger-Orders (1 TSL, 1 TP).")
            assert len(trigger_orders) == 2, f"FEHLER (TSL): Erwartete 2 Trigger-Orders, gefunden {len(trigger_orders)}."
        else:
            # Wenn TSL nicht aktiv ist, erwarten wir 1 fixen SL und 1 TP
            logger.info("Fixer SL-Modus aktiv. Erwarte 2 Trigger-Orders (1 SL, 1 TP).")
            assert len(trigger_orders) == 2, f"FEHLER (Fix SL): Erwartete 2 Trigger-Orders, gefunden {len(trigger_orders)}."
        
        print("-> ✔ Korrekte Anzahl an SL/TP-Trigger-Orders gefunden.")
    except Exception as e:
        pytest.fail(f"Fehler beim Überprüfen der Trigger-Orders: {e}")

    print("\n--- ✅ utbot2 WORKFLOW-TEST ERFOLGREICH! ---")
    # Aufräumen erfolgt automatisch durch die Teardown-Funktion der Fixture
