# code/strategies/envelope/run.py
import os
import sys
import json
import logging
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from utilities.bitget_futures import BitgetFutures
from utilities.strategy_logic import calculate_signals, get_lower_timeframe
from utilities.state_manager import StateManager
from utilities.data_loader import load_data_for_backtest
from utilities.notifications import send_telegram_message

def setup_logging(log_path):
    os.makedirs(log_path.parent, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(levelname)s - %(message)s', handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)])
    logging.Formatter.converter = time.gmtime

def get_active_params(config):
    params = {}
    params.update(config['global_settings'])
    params.update(config['risk_management'])
    params.update(config['strategy_params'])
    logging.info("Aktive Strategie-Parameter erfolgreich geladen.")
    return params

def cleanup_and_check_positions(bitget, symbol, state_manager, telegram_config):
    logging.info(f"Beginne Bereinigung und Positions-Check für {symbol}...")
    try:
        positions = bitget.fetch_open_positions(symbol)
        if positions:
            logging.warning(f"Offene Position für {symbol} gefunden. Schließe sie jetzt...")
            bitget.flash_close_position(symbol)
            message = f"⚠️ **Automatische Schließung** ⚠️\n\nEine bestehende Position für `{symbol}` wurde gefunden und geschlossen."
            send_telegram_message(telegram_config, message)
            time.sleep(5)
    except Exception as e:
        logging.error(f"Fehler beim Schließen der offenen Position: {e}")
        return False
    try:
        open_orders = bitget.fetch_open_orders(symbol)
        if open_orders:
            logging.info(f"{len(open_orders)} offene Limit-Order(s) werden storniert...")
            for order in open_orders: bitget.cancel_order(order['id'], symbol)
        trigger_orders = bitget.fetch_open_trigger_orders(symbol)
        if trigger_orders:
            logging.info(f"{len(trigger_orders)} offene Trigger-Order(s) werden storniert...")
            for order in trigger_orders: bitget.cancel_trigger_order(order['id'], symbol)
    except Exception as e:
        logging.warning(f"Konnte nicht alle Orders stornieren: {e}")
    logging.info("Bereinigung abgeschlossen.")
    state_manager.set_state('ok_to_trade', last_side=None, stop_loss_ids=[])
    return True

def place_trade_logic(bitget, params, side, amount, current_price, telegram_config, state_manager):
    leverage = int(params['calculated_leverage'])
    margin_mode = params['margin_mode']

    order = bitget.place_market_order(params['symbol'], side, amount, leverage=leverage, margin_mode=margin_mode)
    
    filled_price = order.get('price') or order.get('avgFillPrice')
    entry_price = float(filled_price) if filled_price is not None else current_price
    
    logging.info(f"✅ Trade erfolgreich auf dem LIVE-Konto platziert @ {entry_price:.4f}!")

    buffer_pct = 0.1 / 100
    if side == 'buy':
        activation_price = entry_price * (1 + buffer_pct)
    else:
        activation_price = entry_price * (1 - buffer_pct)

    trail_percent = params.get('trailing_tp_percent', 1.0)
    tsl_order = bitget.place_trailing_stop_order(
        symbol=params['symbol'], 
        side='sell' if side == 'buy' else 'buy', 
        amount=amount, 
        trail_percent=trail_percent, 
        activation_price=activation_price
    )
    logging.info(f"✅ Trailing Stop platziert (ID: {tsl_order['id']}). Aktivierungspreis: {activation_price:.4f}")

    message = f"🚀 **Neue Position eröffnet** 🚀\n\nSymbol: `{params['symbol']}`\nTyp: `{side.upper()}`\nEinstieg: `{entry_price:.4f}`\nMenge: `{amount:.4f}`\nHebel: `{leverage}x`"
    send_telegram_message(telegram_config, message)
    state_manager.set_state('in_position', last_side=side, stop_loss_ids=[tsl_order['id']])

def run_test_mode(config, params, api_keys, telegram_config):
    test_params = config['test_mode']
    side_to_test = test_params['side'].lower()
    risk_in_usd = test_params['test_risk_usd']

    logging.warning("="*60 + "\n🚨 LIVE-TEST MODUS AKTIV 🚨\n" + f"Ein {side_to_test.upper()}-Trade wird mit einem Risiko von {risk_in_usd:.2f} USDT erzwungen.\n" + "="*60)
    
    bitget = BitgetFutures(api_keys)
    state_manager = StateManager(str(Path(__file__).parent / 'bot_state.db'))
    
    main_ohlcv_data = load_data_for_backtest(params['symbol'], params['timeframe'], None, None, hide_messages=True)
    ltf_ohlcv_data = load_data_for_backtest(params['symbol'], get_lower_timeframe(params['timeframe']), None, None, hide_messages=True)
    data_with_signals = calculate_signals(main_ohlcv_data, params, ltf_data=ltf_ohlcv_data)
    last_candle = data_with_signals.iloc[-2]
    
    params['calculated_leverage'] = int(last_candle['leverage'])
    logging.info(f"Parameter für Test-Trade: Hebel={params['calculated_leverage']}x, Modus={params['margin_mode']}")

    ticker = bitget.fetch_ticker(params['symbol'])
    current_price = float(ticker['last'])
    atr_for_sl = last_candle['atr']
    sl_price = current_price - (atr_for_sl * params['stop_loss_atr_multiplier']) if side_to_test == 'buy' else current_price + (atr_for_sl * params['stop_loss_atr_multiplier'])
    distance_to_sl = abs(current_price - sl_price)

    if distance_to_sl == 0: raise Exception("Distanz zum SL ist Null.")
    amount = risk_in_usd / distance_to_sl
    
    place_trade_logic(bitget, params, side_to_test, amount, current_price, telegram_config, state_manager)
    
    logging.info(">>> Bot beendet sich jetzt. Test-Modus bleibt AKTIV. Bitte die Position manuell verwalten. <<<")

def run_live_mode(params, api_keys, telegram_config, state_manager):
    bitget = BitgetFutures(api_keys)
    
    main_ohlcv_data = load_data_for_backtest(params['symbol'], params['timeframe'], None, None, hide_messages=True)
    ltf_ohlcv_data = load_data_for_backtest(params['symbol'], get_lower_timeframe(params['timeframe']), None, None, hide_messages=True)
    data_with_signals = calculate_signals(main_ohlcv_data, params, ltf_data=ltf_ohlcv_data)
    
    last_candle = data_with_signals.iloc[-2]
    buy_signal = last_candle['buy_signal']
    sell_signal = last_candle['sell_signal']

    logging.info(f"Prüfe Signale... Status: ok_to_trade. Signal: Buy={buy_signal}, Sell={sell_signal}")
    
    side = None
    if buy_signal and params.get('use_longs', True): side = 'buy'
    elif sell_signal and params.get('use_shorts', True): side = 'sell'
    
    if side:
        logging.info(f"--- NEUES EINSTIEGSSIGNAL: {side.upper()} ---")
        params['calculated_leverage'] = int(last_candle['leverage'])
        
        balance_info = bitget.fetch_balance()
        available_usdt = float(balance_info['USDT']['free'])
        ticker = bitget.fetch_ticker(params['symbol'])
        current_price = float(ticker['last'])
        
        atr_for_sl = last_candle['atr']
        sl_price = current_price - (atr_for_sl * params['stop_loss_atr_multiplier']) if side == 'buy' else current_price + (atr_for_sl * params['stop_loss_atr_multiplier'])
        distance_to_sl = abs(current_price - sl_price)
        if distance_to_sl == 0: raise Exception("Distanz zum SL ist Null.")
        
        risk_amount_usdt = available_usdt * (params['risk_per_trade_percent'] / 100)
        amount = risk_amount_usdt / distance_to_sl
        
        place_trade_logic(bitget, params, side, amount, current_price, telegram_config, state_manager)

def main():
    telegram_config = {}
    try:
        base_path = Path(__file__).parent
        config_path = base_path / 'config.json'
        secret_path = Path.home() / 'utbot2' / 'secret.json'
        
        with open(config_path, 'r') as f: config = json.load(f)
        with open(secret_path, 'r') as f: secrets = json.load(f)
        
        api_keys = secrets['envelope']
        telegram_config = secrets.get('telegram', {})
        
        params = get_active_params(config)
        state_manager = StateManager(str(base_path / 'bot_state.db'))
        bitget = BitgetFutures(api_keys)
        
        is_clean_to_trade = cleanup_and_check_positions(bitget, params['symbol'], state_manager, telegram_config)
        if not is_clean_to_trade: return

        if config.get('test_mode', {}).get('enabled', False):
            run_test_mode(config, params, api_keys, telegram_config)
        else:
            logging.info("Bot im normalen Handelsmodus gestartet.")
            run_live_mode(params, api_keys, telegram_config, state_manager)

    except Exception as e:
        logging.error(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
        message = f"🚨 **UTBot2 FEHLER** 🚨\n\nEin kritischer Fehler hat den Bot gestoppt:\n`{e}`"
        send_telegram_message(telegram_config, message)
            
    logging.info("Bot-Instanz beendet.")

if __name__ == '__main__':
    log_file_path = Path.home() / 'utbot2' / 'logs' / 'envelope.log'
    setup_logging(log_file_path)
    main()
