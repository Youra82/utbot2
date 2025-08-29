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

def run_test_mode(config, params, api_keys):
    test_params = config['test_mode']
    side_to_test = test_params['side'].lower()
    risk_in_usd = test_params['test_risk_usd']

    logging.warning("="*60)
    logging.warning("🚨 LIVE-TEST MODUS AKTIV 🚨")
    logging.warning(f"Ein {side_to_test.upper()}-Trade wird mit einem Risiko von {risk_in_usd:.2f} USDT erzwungen.")
    logging.warning("="*60)
    
    bitget = BitgetFutures(api_keys)
    
    main_ohlcv_data = load_data_for_backtest(params['symbol'], params['timeframe'], None, None, hide_messages=True)
    ltf_ohlcv_data = load_data_for_backtest(params['symbol'], get_lower_timeframe(params['timeframe']), None, None, hide_messages=True)
    data_with_signals = calculate_signals(main_ohlcv_data, params, ltf_data=ltf_ohlcv_data)
    last_candle = data_with_signals.iloc[-2]
    
    leverage_for_this_trade = int(last_candle['leverage'])
    margin_mode = params['margin_mode']
    
    bitget.set_margin_mode(params['symbol'], margin_mode=margin_mode)
    bitget.set_leverage(params['symbol'], leverage=leverage_for_this_trade, margin_mode=margin_mode)
    logging.info(f"Dynamischer Hebel ({leverage_for_this_trade}x) und Margin-Modus ({margin_mode}) für Test-Trade gesetzt.")

    ticker = bitget.fetch_ticker(params['symbol'])
    current_price = float(ticker['last'])
    atr_for_sl = last_candle['atr']
    sl_price = current_price - (atr_for_sl * params['stop_loss_atr_multiplier']) if side_to_test == 'buy' else current_price + (atr_for_sl * params['stop_loss_atr_multiplier'])
    distance_to_sl = abs(current_price - sl_price)

    if distance_to_sl == 0:
        raise Exception("Distanz zum SL ist Null. Test abgebrochen.")
        
    amount = risk_in_usd / distance_to_sl
    
    logging.info(f"Platziere Test-Market-Order ({side_to_test.upper()}) für {amount:.4f} Coins...")
    order = bitget.place_market_order(params['symbol'], side_to_test, amount)
    entry_price = float(order.get('price', order.get('avgFillPrice', current_price)))
    logging.info(f"✅ Test-Trade erfolgreich auf dem LIVE-Konto platziert @ {entry_price:.4f}!")
    
    trail_percent = params.get('trailing_tp_percent', 1.0)
    tsl_order = bitget.place_trailing_stop_order(
        symbol=params['symbol'], 
        side='sell' if side_to_test == 'buy' else 'buy', 
        amount=amount, 
        trail_percent=trail_percent, 
        activation_price=entry_price
    )
    logging.info(f"✅ Trailing Stop für Test-Trade platziert (ID: {tsl_order['id']}).")
    
    config['test_mode']['enabled'] = False
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)
    logging.warning("Live-Test Modus wurde in der config.json automatisch deaktiviert.")
    logging.info(">>> Bot beendet sich jetzt. Bitte die Position manuell verwalten. <<<")

def run_live_mode(params, api_keys, telegram_config):
    bitget = BitgetFutures(api_keys)
    state_manager = StateManager(str(Path(__file__).parent / 'bot_state.db'))
    
    current_state = state_manager.get_state()
    in_position = current_state.get('status') == 'in_position'
    
    main_ohlcv_data = load_data_for_backtest(params['symbol'], params['timeframe'], None, None, hide_messages=True)
    ltf_ohlcv_data = load_data_for_backtest(params['symbol'], get_lower_timeframe(params['timeframe']), None, None, hide_messages=True)
    data_with_signals = calculate_signals(main_ohlcv_data, params, ltf_data=ltf_ohlcv_data)
    
    last_candle = data_with_signals.iloc[-2]
    buy_signal = last_candle['buy_signal']
    sell_signal = last_candle['sell_signal']

    logging.info(f"Prüfe Signale... Status: {current_state.get('status')}. Signal: Buy={buy_signal}, Sell={sell_signal}")

    if in_position:
        position_side = current_state.get('last_side')
        if (position_side == 'buy' and sell_signal) or (position_side == 'sell' and buy_signal):
            logging.info(f"--- GEGENSIGNAL ERKANNT: Schließe Position ---")
            close_order = bitget.flash_close_position(params['symbol'])
            price_str = f"{float(close_order.get('price', 0.0)):.4f}"
            message = f"✅ **Position geschlossen (Gegensignal)** ✅\n\nSymbol: `{params['symbol']}`\nTyp: `{position_side.upper()}`\nSchlusskurs: `{price_str}`"
            send_telegram_message(telegram_config, message)
            state_manager.set_state('ok_to_trade', last_side=None, stop_loss_ids=[])
    
    elif not in_position:
        side = None
        if buy_signal and params.get('use_longs', True): side = 'buy'
        elif sell_signal and params.get('use_shorts', True): side = 'sell'
        
        if side:
            logging.info(f"--- NEUES EINSTIEGSSIGNAL: {side.upper()} ---")
            leverage_for_this_trade = int(last_candle['leverage'])
            margin_mode = params['margin_mode']
            
            bitget.set_margin_mode(params['symbol'], margin_mode=margin_mode)
            bitget.set_leverage(params['symbol'], leverage=leverage_for_this_trade, margin_mode=margin_mode)
            
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
            
            order = bitget.place_market_order(params['symbol'], side, amount)
            entry_price = float(order.get('price', order.get('avgFillPrice', current_price)))

            tsl_order = bitget.place_trailing_stop_order(symbol=params['symbol'], side='sell' if side == 'buy' else 'buy', amount=amount, trail_percent=params['trailing_tp_percent'], activation_price=entry_price)
            
            message = f"🚀 **Neue Position eröffnet** 🚀\n\nSymbol: `{params['symbol']}`\nTyp: `{side.upper()}`\nEinstieg: `{entry_price:.4f}`\nMenge: `{amount:.4f}`\nHebel: `{leverage_for_this_trade}x`"
            send_telegram_message(telegram_config, message)
            state_manager.set_state('in_position', last_side=side, stop_loss_ids=[tsl_order['id']])

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

        if config.get('test_mode', {}).get('enabled', False):
            run_test_mode(config, params, api_keys)
        else:
            logging.info("Bot im normalen Handelsmodus gestartet.")
            run_live_mode(params, api_keys, telegram_config)

    except Exception as e:
        logging.error(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
        message = f"🚨 **UTBot2 FEHLER** 🚨\n\nEin kritischer Fehler hat den Bot gestoppt:\n`{e}`"
        send_telegram_message(telegram_config, message)
            
    logging.info("Bot-Instanz beendet.")

if __name__ == '__main__':
    log_file_path = Path.home() / 'utbot2' / 'logs' / 'envelope.log'
    setup_logging(log_file_path)
    main()
