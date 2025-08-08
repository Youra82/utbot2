# run.py
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from utilities.bitget_futures import BitgetFutures

# --- CONFIG ---
params = {
    'symbol': 'BTC/USDT:USDT',
    'timeframe': '1h',
    'margin_mode': 'isolated',
    'balance_fraction': 1,
    'leverage': 1,
    'use_longs': True,
    'use_shorts': True,
    'stop_loss_pct': 0.4,
    # UT Bot Alerts Parameter
    'ut_key_value': 1,          # Sensitivität des ATR Multiplikators
    'ut_atr_period': 10,        # ATR Periode
    'ut_heiken_ashi': False,    # Heikin-Ashi Kerzen verwenden
    'trade_size_pct': 100,      # Einsatzgröße in % des verfügbaren Guthabens
}

# Pfade von LiveTradingBots zu utbot2 geändert
key_path = 'utbot2/secret.json'
key_name = 'envelope'

tracker_file = f"utbot2/code/strategies/envelope/tracker_{params['symbol'].replace('/', '-').replace(':', '-')}.json"

# --- AUTHENTICATION ---
print(f"\n{datetime.now().strftime('%H:%M:%S')}: >>> starting execution for {params['symbol']}")
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
print(f"{datetime.now().strftime('%H:%M:%S')}: all orders cancelled")

# --- UT BOT ALERTS LOGIC ---
def calculate_heikin_ashi(data):
    ha_data = pd.DataFrame(index=data.index)
    
    # Erste Kerze: Normale Werte
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
    # Heikin-Ashi berechnen wenn aktiviert
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
    pos = [0] * len(data)
    
    for i in range(len(data)):
        if i == 0:
            x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i] if src.iloc[i] > 0 else src.iloc[i] + n_loss.iloc[i]
            pos[i] = 0
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
            
            # Positionslogik
            if src.iloc[i-1] < x_atr_trailing_stop[i-1] and src.iloc[i] > x_atr_trailing_stop[i]:
                pos[i] = 1
            elif src.iloc[i-1] > x_atr_trailing_stop[i-1] and src.iloc[i] < x_atr_trailing_stop[i]:
                pos[i] = -1
            else:
                pos[i] = pos[i-1]
    
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    data['position'] = pos
    
    # Signale generieren
    data['buy_signal'] = False
    data['sell_signal'] = False
    
    for i in range(1, len(data)):
        # Long Signal: Preis über Trailing Stop + Crossover
        if (data['close'].iloc[i] > data['x_atr_trailing_stop'].iloc[i] and 
            data['close'].iloc[i-1] <= data['x_atr_trailing_stop'].iloc[i-1]):
            data.loc[data.index[i], 'buy_signal'] = True
        
        # Short Signal: Preis unter Trailing Stop + Crossunder
        if (data['close'].iloc[i] < data['x_atr_trailing_stop'].iloc[i] and 
            data['close'].iloc[i-1] >= data['x_atr_trailing_stop'].iloc[i-1]):
            data.loc[data.index[i], 'sell_signal'] = True
    
    return data

# --- FETCH DATA AND CALCULATE SIGNALS ---
data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], 500)
data = calculate_ut_signals(data, params)

# Get last signal
last_row = data.iloc[-1]
buy_signal = last_row['buy_signal']
sell_signal = last_row['sell_signal']
print(f"{datetime.now().strftime('%H:%M:%S')}: last signal - "
      f"Buy: {buy_signal}, Sell: {sell_signal}")

# --- CHECK OPEN POSITIONS ---
positions = bitget.fetch_open_positions(params['symbol'])
open_position = len(positions) > 0

if open_position:
    position = positions[0]
    position_side = position['side']
    print(f"{datetime.now().strftime('%H:%M:%S')}: open {position_side} position")
else:
    position_side = None

# --- EXECUTE TRADES ---
tracker_info = read_tracker_file(tracker_file)
current_time = datetime.now().strftime('%H:%M:%S')

if tracker_info['status'] != "ok_to_trade":
    print(f"{current_time}: status is {tracker_info['status']}, skipping trading")
    sys.exit()

# Fetch balance and calculate trade size
balance = bitget.fetch_balance()['USDT']['total']
trade_size = (balance * params['trade_size_pct'] / 100) * params['leverage']
print(f"{current_time}: available balance: {balance}, trade size: {trade_size}")

# Close opposite position if exists
if open_position:
    if (position_side == 'long' and sell_signal) or (position_side == 'short' and buy_signal):
        bitget.flash_close_position(params['symbol'])
        print(f"{current_time}: closed {position_side} position due to opposite signal")
        open_position = False

# Open new positions
if not open_position:
    if buy_signal and params['use_longs']:
        # Place market buy order
        bitget.place_market_order(params['symbol'], 'buy', trade_size)
        print(f"{current_time}: opened long position")
        
        # Place stop loss
        current_price = last_row['close']
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
    
    elif sell_signal and params['use_shorts']:
        # Place market sell order
        bitget.place_market_order(params['symbol'], 'sell', trade_size)
        print(f"{current_time}: opened short position")
        
        # Place stop loss
        current_price = last_row['close']
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

print(f"{datetime.now().strftime('%H:%M:%S')}: <<< execution complete")
