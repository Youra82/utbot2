# run.py
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
import pytz
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from utilities.bitget_futures import BitgetFutures

# --- CONFIG ---
params = {
    'symbol': 'BTC/USDT:USDT',
    'timeframe': '15m',
    'margin_mode': 'isolated',
    'balance_fraction': 1,
    'leverage': 1,
    'use_longs': True,
    'use_shorts': True,
    'stop_loss_pct': 0.4,
    'enable_stop_loss': False,
    'signal_lookback_period': 6,
    'min_signal_confirmation': 0.2,
    'max_price_change_pct': 2.5,
    'ut_key_value': 1,
    'ut_atr_period': 10,
    'ut_heiken_ashi': False,
    'trade_size_pct': 100,
}

# Pfade anpassen
key_path = 'utbot2/secret.json'
key_name = 'envelope'

tracker_file = f"utbot2/code/strategies/envelope/tracker_{params['symbol'].replace('/', '-').replace(':', '-')}.json"

# --- AUTHENTICATION ---
current_utc = datetime.now(timezone.utc)
print(f"\n{current_utc.strftime('%H:%M:%S')} UTC: >>> starting execution for {params['symbol']}")
with open(key_path, "r") as f:
    api_setup = json.load(f)[key_name]
bitget = BitgetFutures(api_setup)

# --- TRACKER FILE ---
if not os.path.exists(tracker_file):
    with open(tracker_file, 'w') as file:
        json.dump({"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}, file)

def read_tracker_file(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def update_tracker_file(file_path, data):
    with open(file_path, 'w') as file:
        json.dump(data, file)

# --- CANCEL OPEN ORDERS ---
orders = bitget.fetch_open_orders(params['symbol'])
for order in orders:
    bitget.cancel_order(order['id'], params['symbol'])
trigger_orders = bitget.fetch_open_trigger_orders(params['symbol'])
for order in trigger_orders:
    bitget.cancel_trigger_order(order['id'], params['symbol'])
print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC: all orders cancelled")

# --- UT BOT ALERTS LOGIC ---
def calculate_heikin_ashi(data):
    ha_data = pd.DataFrame(index=data.index)
    
    if not data.empty:
        ha_close = (data['open'] + data['high'] + data['low'] + data['close']) / 4
        ha_open = (data['open'].iloc[0] + data['close'].iloc[0]) / 2
        
        ha_data['ha_open'] = np.nan
        ha_data['ha_high'] = np.nan
        ha_data['ha_low'] = np.nan
        ha_data['ha_close'] = ha_close
        
        for i in range(len(data)):
            if i == 0:
                ha_data.iloc[0, ha_data.columns.get_loc('ha_open')] = ha_open
            else:
                ha_open = (ha_data['ha_open'].iloc[i-1] + ha_data['ha_close'].iloc[i-1]) / 2
                ha_data.iloc[i, ha_data.columns.get_loc('ha_open')] = ha_open
            
            ha_high = max(data['high'].iloc[i], ha_data['ha_open'].iloc[i], ha_data['ha_close'].iloc[i])
            ha_low = min(data['low'].iloc[i], ha_data['ha_open'].iloc[i], ha_data['ha_close'].iloc[i])
            
            ha_data.iloc[i, ha_data.columns.get_loc('ha_high')] = ha_high
            ha_data.iloc[i, ha_data.columns.get_loc('ha_low')] = ha_low
    
    return ha_data

def calculate_ut_signals(data, params):
    if params['ut_heiken_ashi']:
        ha_data = calculate_heikin_ashi(data)
        src = ha_data['ha_close']
    else:
        src = data['close']
    
    # ATR berechnen
    data['atr'] = ta.volatility.average_true_range(
        data['high'], data['low'], data['close'], 
        window=params['ut_atr_period']
    )
    
    n_loss = params['ut_key_value'] * data['atr']
    
    # Trailing Stop berechnen
    x_atr_trailing_stop = [0.0] * len(data)
    
    for i in range(len(data)):
        if i == 0:
            x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
        else:
            prev_stop = x_atr_trailing_stop[i-1]
            
            if src.iloc[i] > prev_stop and src.iloc[i-1] > prev_stop:
                x_atr_trailing_stop[i] = max(prev_stop, src.iloc[i] - n_loss.iloc[i])
            elif src.iloc[i] < prev_stop and src.iloc[i-1] < prev_stop:
                x_atr_trailing_stop[i] = min(prev_stop, src.iloc[i] + n_loss.iloc[i])
            else:
                if src.iloc[i] > prev_stop:
                    x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
                else:
                    x_atr_trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    
    # Signale generieren (korrigierte Logik gemäß TradingView)
    data['buy_signal'] = False
    data['sell_signal'] = False
    
    for i in range(1, len(data)):
        # Kaufsignal: Close kreuzt über x_atr_trailing_stop
        if (data['close'].iloc[i] > data['x_atr_trailing_stop'].iloc[i] and 
            data['close'].iloc[i-1] <= data['x_atr_trailing_stop'].iloc[i-1]):
            data.loc[data.index[i], 'buy_signal'] = True
        
        # Verkaufssignal: Close kreuzt unter x_atr_trailing_stop
        if (data['close'].iloc[i] < data['x_atr_trailing_stop'].iloc[i] and 
            data['close'].iloc[i-1] >= data['x_atr_trailing_stop'].iloc[i-1]):
            data.loc[data.index[i], 'sell_signal'] = True
    
    return data

# --- FETCH DATA AND CALCULATE SIGNALS ---
# Warte bis Kerze mindestens 1 Minute alt ist (für 15m-Kerzen)
now = datetime.now(timezone.utc)
candle_duration = timedelta(minutes=15)
seconds_since_candle = (now.minute % 15 * 60 + now.second) if now.minute >= 0 else 0

if seconds_since_candle < 60:
    print(f"{now.strftime('%H:%M:%S')} UTC: Too early in new candle ({seconds_since_candle}s), skipping execution")
    sys.exit()

# Mehr Kerzen holen für Rückblick
lookback_candles = max(100, params['signal_lookback_period'] + 20)
data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], lookback_candles)

# Zeitzonen für Index setzen
data.index = data.index.tz_localize('UTC')
data = calculate_ut_signals(data, params)

# Diagnostische Ausgabe
print("\nLast 6 candles signals:")
print(data[['close', 'x_atr_trailing_stop', 'buy_signal', 'sell_signal']].tail(6))

# Signalerkennung mit verbesserten Bedingungen
current_time = datetime.now(timezone.utc)
signals = []
timeframe_minutes = {
    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '2h': 120, '4h': 240, '1d': 1440
}
candle_duration = timedelta(minutes=timeframe_minutes.get(params['timeframe'], 60))

for i in range(1, min(params['signal_lookback_period'] + 1, len(data))):
    idx = -i
    candle_time = data.index[idx]
    
    # Kerzenfortschritt prüfen
    time_elapsed = current_time - candle_time
    candle_completion = min(1.0, time_elapsed.total_seconds() / candle_duration.total_seconds())
    
    # Nur signifikant fortgeschrittene Kerzen berücksichtigen
    if candle_completion >= params['min_signal_confirmation']:
        if data.iloc[idx]['buy_signal']:
            signals.append(('buy', candle_time, data.iloc[idx]['close']))
        elif data.iloc[idx]['sell_signal']:
            signals.append(('sell', candle_time, data.iloc[idx]['close']))

print(f"\n{current_time.strftime('%H:%M:%S')} UTC: found {len(signals)} signals in last {params['signal_lookback_period']} candles")

# Entscheidungslogik
buy_signal = False
sell_signal = False
signal_used = None

if signals:
    latest_signal = signals[-1]
    signal_type, signal_time, signal_price = latest_signal
    
    current_price = data.iloc[-1]['close']
    price_change = abs(current_price - signal_price) / signal_price * 100
    
    if price_change < params['max_price_change_pct']:
        if signal_type == 'buy':
            buy_signal = True
        else:
            sell_signal = True
        signal_used = f"{signal_type} signal from {signal_time.strftime('%Y-%m-%d %H:%M')} UTC (Δ: {price_change:.2f}%)"
        print(f"{current_time.strftime('%H:%M:%S')} UTC: using {signal_used}")
    else:
        print(f"{current_time.strftime('%H:%M:%S')} UTC: signal expired (Δ {price_change:.2f}% > limit {params['max_price_change_pct']}%)")
else:
    print(f"{current_time.strftime('%H:%M:%S')} UTC: no valid signals found")

# --- CHECK OPEN POSITIONS ---
positions = bitget.fetch_open_positions(params['symbol'])
open_position = len(positions) > 0

if open_position:
    position = positions[0]
    position_side = position['side']
    position_size = float(position['contracts']) * float(position['contractSize'])
    entry_price = float(position['entryPrice'])
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC: open {position_side} position - Size: {position_size:.4f}, Entry: {entry_price:.2f}")
else:
    position_side = None

# Debug-Info
print(f"\nTrade Decision Summary:")
print(f"Buy Signal: {buy_signal} | Sell Signal: {sell_signal}")
print(f"Open Position: {open_position} | Position Side: {position_side}")
print(f"Use Longs: {params['use_longs']} | Use Shorts: {params['use_shorts']}")

# --- EXECUTE TRADES ---
tracker_info = read_tracker_file(tracker_file)
current_time_utc = datetime.now(timezone.utc).strftime('%H:%M:%S')

if tracker_info['status'] != "ok_to_trade":
    print(f"{current_time_utc} UTC: status is {tracker_info['status']}, skipping trading")
    sys.exit()

# Kontostand abrufen
balance_info = bitget.fetch_balance()
balance = balance_info['USDT']['total']
trade_size = (balance * params['trade_size_pct'] / 100) * params['leverage']
print(f"{current_time_utc} UTC: available balance: {balance:.2f} USDT, trade size: {trade_size:.2f} USDT")

# Gegenläufige Position schließen
if open_position:
    if (position_side == 'long' and sell_signal) or (position_side == 'short' and buy_signal):
        bitget.flash_close_position(params['symbol'])
        print(f"{current_time_utc} UTC: closed {position_side} position due to opposite signal")
        open_position = False
        update_tracker_file(tracker_file, {
            "status": "ok_to_trade",
            "last_side": None,
            "stop_loss_ids": []
        })

# Neue Position eröffnen
if not open_position:
    if buy_signal and params['use_longs']:
        bitget.place_market_order(params['symbol'], 'buy', trade_size)
        print(f"{current_time_utc} UTC: opened long position based on {signal_used}")
        
        if params['enable_stop_loss']:
            current_price = data.iloc[-1]['close']
            stop_loss_price = current_price * (1 - params['stop_loss_pct'])
            sl_order = bitget.place_trigger_market_order(
                symbol=params['symbol'],
                side='sell',
                amount=trade_size,
                trigger_price=stop_loss_price,
                reduce=True
            )
            update_tracker_file(tracker_file, {
                "status": "ok_to_trade",
                "last_side": "long",
                "stop_loss_ids": [sl_order['id']]
            })
            print(f"{current_time_utc} UTC: placed stop-loss at {stop_loss_price:.2f}")
        else:
            update_tracker_file(tracker_file, {
                "status": "ok_to_trade",
                "last_side": "long",
                "stop_loss_ids": []
            })
    
    elif sell_signal and params['use_shorts']:
        bitget.place_market_order(params['symbol'], 'sell', trade_size)
        print(f"{current_time_utc} UTC: opened short position based on {signal_used}")
        
        if params['enable_stop_loss']:
            current_price = data.iloc[-1]['close']
            stop_loss_price = current_price * (1 + params['stop_loss_pct'])
            sl_order = bitget.place_trigger_market_order(
                symbol=params['symbol'],
                side='buy',
                amount=trade_size,
                trigger_price=stop_loss_price,
                reduce=True
            )
            update_tracker_file(tracker_file, {
                "status": "ok_to_trade",
                "last_side": "short",
                "stop_loss_ids": [sl_order['id']]
            })
            print(f"{current_time_utc} UTC: placed stop-loss at {stop_loss_price:.2f}")
        else:
            update_tracker_file(tracker_file, {
                "status": "ok_to_trade",
                "last_side": "short",
                "stop_loss_ids": []
            })

print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC: <<< execution complete\n")
