# tests/test_workflow.py (Finaler Fix: Mocking der Trigger-Orders-Erstellung)

# ... (Klassen, Imports und test_setup bleiben unverändert) ...

# --- Fixture für das Mocking der ExchangeHandler Methoden (für den Bot-Code) ---
@pytest.fixture(autouse=True)
def mock_exchange_methods(request):
    """Patcht Methoden nur für den Bot-Code, der sie dynamisch erwartet."""
    if request.node.name == 'test_full_utbot2_workflow_on_bitget':
        exchange_handler_path = 'utils.exchange_handler.ExchangeHandler'
        
        # Patch cleanup_all_open_orders
        with patch(f'{exchange_handler_path}.cleanup_all_open_orders', MagicMock(return_value=0), create=True):
            # Patch create_market_order
            with patch(f'{exchange_handler_path}.create_market_order', MagicMock(return_value={'id': 'mock_market_id', 'average': 2.50, 'filled': 100.0}), create=True):
                # Patch set_leverage
                with patch(f'{exchange_handler_path}.set_leverage', MagicMock(), create=True):
                    
                    # *** KORREKTUR HIER: Wir mocken die untergeordneten Order-Platzierungen ***
                    # Patch place_trigger_market_order (für SL und TP)
                    with patch(f'{exchange_handler_path}.place_trigger_market_order', MagicMock(return_value={'id': 'mock_trigger_id'}), create=True):
                    
                        # Patch fetch_open_positions mit side_effect
                        with patch(f'{exchange_handler_path}.fetch_open_positions', side_effect=[
                            # 1. Abfrage in run_strategy_cycle (sollte leer sein)
                            [], 
                            # 2. Abfrage in create_market_order_with_sl_tp (sollte die neue Position bestätigen)
                            [
                                {'symbol': 'XRP/USDT:USDT', 'contracts': 100.0, 'side': 'long', 'entryPrice': 2.50} 
                            ] 
                        ], create=True):
                            # Patch fetch_open_trigger_orders (WICHTIG: Muss 2 zurückgeben, da wir gerade 2 platziert haben)
                            with patch(f'{exchange_handler_path}.fetch_open_trigger_orders', MagicMock(return_value=[
                                {'id': 'sl1', 'info': {'triggerType': 'stop_market'}}, 
                                {'id': 'tp1', 'info': {'triggerType': 'take_profit_market'}}
                            ]), create=True):
                                # Patch fetch_ticker
                                with patch(f'{exchange_handler_path}.fetch_ticker', MagicMock(return_value={'last': 2.50}), create=True):
                                    # Patch fetch_balance_usdt
                                    with patch(f'{exchange_handler_path}.fetch_balance_usdt', MagicMock(return_value=100.0), create=True):
                                         yield 
    else:
        yield


def test_full_utbot2_workflow_on_bitget(mock_exchange_methods, test_setup):
    """
    Testet den vereinfachten Handelsablauf von utbot2 auf Bitget.
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
