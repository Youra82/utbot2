# /home/ubuntu/utbot2/code/strategies/envelope/run.py
import os
import sys
import json
import time
import logging
from pathlib import Path

# Füge das Hauptverzeichnis zum Python-Pfad hinzu, damit wir die Utilities importieren können
sys.path.append(str(Path(__file__).parent.parent.parent))

from utilities.bitget_futures import BitgetFutures
from utilities.strategy_logic import calculate_signals
from utilities.state_manager import StateManager

# --- Logging Konfiguration ---
def setup_logging(log_path):
    os.makedirs(log_path.parent, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s UTC: %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.Formatter.converter = time.gmtime # Logs in UTC anzeigen

def run_single_check():
    """Führt eine einzelne Prüfung auf Handelssignale durch und beendet sich dann."""
    
    # --- 1. Konfiguration & Initialisierung ---
    try:
        base_path = Path(__file__).parent
        config_path = base_path / 'config.json'
        secret_path = Path.home() / 'utbot2' / 'secret.json'
        
        with open(config_path, 'r') as f:
            params = json.load(f)
        
        with open(secret_path, 'r') as f:
            api_keys = json.load(f)['envelope']

        bitget = BitgetFutures(api_keys)
        logging.info(f"Bot-Instanz gestartet. Handel für {params['symbol']} auf dem {params['timeframe']} Timeframe.")
        
        if params.get('use_dynamic_leverage', False):
            logging.info(f"Dynamischer Hebel aktiviert. Spanne: {params.get('min_leverage')}x - {params.get('max_leverage')}x")
        else:
            logging.info(f"Fester Hebel wird verwendet: {params.get('leverage')}x")

        db_path = base_path / 'bot_state.db'
        state_manager = StateManager(str(db_path))
        logging.info("State Manager initialisiert.")

    except Exception as e:
        logging.error(f"Fehler bei der Initialisierung: {e}")
        return # Beende den Bot, wenn die Konfiguration nicht geladen werden kann

    # --- 2. Die eigentliche Logik (ohne Schleife) ---
    try:
        current_state = state_manager.get_state()
        in_position = current_state['status'] == 'in_position'
        
        # --- 3. Daten abrufen und Signale berechnen ---
        ohlcv_data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], limit=100)
        data_with_signals = calculate_signals(ohlcv_data, params)
        
        last_candle = data_with_signals.iloc[-2]
        buy_signal = last_candle['buy_signal']
        sell_signal = last_candle['sell_signal']

        logging.info(f"Prüfe Signale... Status: {current_state['status']}. Signal: Buy={buy_signal}, Sell={sell_signal}")

        # --- 4. Die Handelslogik (Das Gehirn) ---
        
        # FALL 1: EINSTIEGSSIGNAL
        if not in_position:
            side = None
            if buy_signal: side = 'buy'
            elif sell_signal: side = 'sell'
            
            if side:
                logging.info(f"--- NEUES HANDELSSIGNAL: {side.upper()} ---")
                
                leverage_for_this_trade = int(last_candle['leverage'])
                bitget.set_leverage(params['symbol'], leverage_for_this_trade)
                logging.info(f"Dynamischer Hebel für diesen Trade auf {leverage_for_this_trade}x gesetzt.")
                
                risk_percent = params.get('risk_per_trade_percent', 5.0)
                balance_info = bitget.fetch_balance()
                available_usdt = float(balance_info['USDT']['free'])
                current_price = float(bitget.fetch_ticker(params['symbol'])['last'])
                
                sl_multiplier = params['stop_loss_atr_multiplier']
                atr_for_sl = last_candle['atr']
                
                if side == 'buy':
                    sl_price = current_price - (atr_for_sl * sl_multiplier)
                else:
                    sl_price = current_price + (atr_for_sl * sl_multiplier)

                distance_to_sl = abs(current_price - sl_price)
                if distance_to_sl == 0:
                    raise Exception("Distanz zum Stop-Loss ist Null. Trade wird abgebrochen.")

                risk_amount_usdt = available_usdt * (risk_percent / 100)
                amount = risk_amount_usdt / distance_to_sl
                
                order = bitget.place_market_order(params['symbol'], side, amount)
                entry_price = float(order.get('price', order.get('avgFillPrice', current_price)))
                logging.info(f"Position eröffnet: {side.upper()} @ {entry_price:.4f} | Menge: {amount:.4f}")
                
                sl_order = bitget.place_trigger_market_order(params['symbol'], 'sell' if side == 'buy' else 'buy', amount, sl_price, reduce=True)
                logging.info(f"Stop-Loss Order platziert bei {sl_price:.4f} (ID: {sl_order['id']})")
                
                state_manager.set_state('in_position', last_side=side, stop_loss_ids=[sl_order['id']])
        
        # FALL 2: AUSSTIEGSSIGNAL
        elif in_position:
            position_side = current_state['last_side']
            
            if (position_side == 'buy' and sell_signal) or (position_side == 'short' and buy_signal):
                logging.info(f"--- GEGENSIGNAL ERKANNT: Schließe Position ---")
                
                for sl_id in current_state['stop_loss_ids']:
                    try:
                        bitget.cancel_trigger_order(sl_id, params['symbol'])
                        logging.info(f"Stop-Loss Order {sl_id} erfolgreich gelöscht.")
                    except Exception as e:
                        logging.warning(f"Konnte SL-Order {sl_id} nicht löschen (evtl. bereits ausgelöst): {e}")
                
                close_order = bitget.flash_close_position(params['symbol'])
                logging.info(f"Position geschlossen bei ca. {close_order.get('price', 'N/A'):.4f}")
                
                state_manager.set_state('ok_to_trade', last_side=None, stop_loss_ids=[])

    except Exception as e:
        logging.error(f"Ein Fehler ist aufgetreten: {e}")
    
    logging.info("Bot-Instanz beendet.")

if __name__ == '__main__':
    log_file_path = Path.home() / 'utbot2' / 'logs' / 'envelope.log'
    setup_logging(log_file_path)
    run_single_check()
