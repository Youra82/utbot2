# code/strategies/envelope/run.py
import os
import sys
import json
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from utilities.bitget_futures import BitgetFutures
from utilities.strategy_logic import calculate_signals, get_lower_timeframe
from utilities.state_manager import StateManager
from utilities.data_loader import load_data_for_backtest

def setup_logging(log_path):
    os.makedirs(log_path.parent, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(levelname)s - %(message)s', handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)])
    logging.Formatter.converter = time.gmtime

def run_single_check():
    try:
        base_path = Path(__file__).parent
        config_path = base_path / 'config.json'
        secret_path = Path.home() / 'utbot2' / 'secret.json'
        
        with open(config_path, 'r') as f: params = json.load(f)
        with open(secret_path, 'r') as f: api_keys = json.load(f)['envelope']

        bitget = BitgetFutures(api_keys)
        logging.info(f"Bot-Instanz gestartet. Handel für {params['symbol']} auf dem {params['timeframe']} Timeframe.")
        
        db_path = base_path / 'bot_state.db'
        state_manager = StateManager(str(db_path))
        logging.info("State Manager initialisiert.")

    except Exception as e:
        logging.error(f"Fehler bei der Initialisierung: {e}")
        return

    try:
        current_state = state_manager.get_state()
        in_position = current_state.get('status') == 'in_position'
        
        main_timeframe = params['timeframe']
        lower_timeframe = get_lower_timeframe(main_timeframe)
        
        # Für den Live-Bot brauchen wir kein Start-/Enddatum, None ist hier korrekt
        main_ohlcv_data = load_data_for_backtest(params['symbol'], main_timeframe, None, None, hide_messages=True)
        
        ltf_ohlcv_data = None
        if lower_timeframe:
            ltf_ohlcv_data = load_data_for_backtest(params['symbol'], lower_timeframe, None, None, hide_messages=True)
        
        data_with_signals = calculate_signals(main_ohlcv_data, params, ltf_data=ltf_ohlcv_data)
        
        last_candle = data_with_signals.iloc[-2]
        buy_signal = last_candle['buy_signal']
        sell_signal = last_candle['sell_signal']

        logging.info(f"Prüfe Signale... Status: {current_state.get('status')}. Signal: Buy={buy_signal}, Sell={sell_signal}")

        if in_position:
            position_side = current_state.get('last_side')
            if (position_side == 'buy' and sell_signal) or (position_side == 'short' and buy_signal):
                logging.info(f"--- GEGENSIGNAL ERKANNT: Schließe Position ---")
                for stop_id in current_state.get('stop_loss_ids', []):
                    try:
                        bitget.cancel_trigger_order(stop_id, params['symbol'])
                        logging.info(f"Trailing Stop Order {stop_id} erfolgreich gelöscht.")
                    except Exception as e:
                        logging.warning(f"Konnte Trailing Stop Order {stop_id} nicht löschen: {e}")
                close_order = bitget.flash_close_position(params['symbol'])
                logging.info(f"Position durch Gegensignal geschlossen bei ca. {close_order.get('price', 'N/A'):.4f}")
                state_manager.set_state('ok_to_trade', last_side=None, stop_loss_ids=[])
        elif not in_position:
            side = None
            if buy_signal: side = 'buy'
            elif sell_signal: side = 'sell'
            if side:
                logging.info(f"--- NEUES EINSTIEGSSIGNAL: {side.upper()} ---")
                leverage_for_this_trade = int(last_candle['leverage'])
                bitget.set_leverage(params['symbol'], leverage_for_this_trade)
                logging.info(f"Hebel für diesen Trade auf {leverage_for_this_trade}x gesetzt.")
                balance_info = bitget.fetch_balance()
                available_usdt = float(balance_info['USDT']['free'])
                ticker = bitget.fetch_ticker(params['symbol'])
                if ticker is None or ticker.get('last') is None:
                    raise Exception(f"Konnte keinen gültigen Preis für {params['symbol']} abrufen.")
                current_price = float(ticker['last'])
                sl_multiplier = params['stop_loss_atr_multiplier']
                atr_for_sl = last_candle['atr']
                if side == 'buy': sl_price = current_price - (atr_for_sl * sl_multiplier)
                else: sl_price = current_price + (atr_for_sl * sl_multiplier)
                distance_to_sl = abs(current_price - sl_price)
                if distance_to_sl == 0: raise Exception("Distanz zum SL ist Null.")
                risk_percent = params.get('risk_per_trade_percent', 5.0)
                risk_amount_usdt = available_usdt * (risk_percent / 100)
                amount = risk_amount_usdt / distance_to_sl
                order = bitget.place_market_order(params['symbol'], side, amount)
                entry_price = float(order.get('price', order.get('avgFillPrice', current_price)))
                logging.info(f"Position eröffnet: {side.upper()} @ {entry_price:.4f} | Menge: {amount:.4f}")
                trail_percent = params.get('trailing_tp_percent', 1.0)
                tsl_order = bitget.place_trailing_stop_order(symbol=params['symbol'], side='sell' if side == 'buy' else 'buy', amount=amount, trail_percent=trail_percent, activation_price=entry_price)
                logging.info(f"Trailing Stop Order platziert mit {trail_percent}% Abstand (ID: {tsl_order['id']})")
                state_manager.set_state('in_position', last_side=side, stop_loss_ids=[tsl_order['id']])
    except Exception as e:
        logging.error(f"Ein Fehler ist aufgetreten: {e}")
    logging.info("Bot-Instanz beendet.")

if __name__ == '__main__':
    log_file_path = Path.home() / 'utbot2' / 'logs' / 'envelope.log'
    setup_logging(log_file_path)
    run_single_check()
