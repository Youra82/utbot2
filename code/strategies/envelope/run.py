# run.py
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timedelta

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
    'enable_stop_loss': True,
    # Verbesserte Signalerkennung
    'signal_lookback_period': 2,  # Anzahl der Kerzen zurück
    'min_signal_confirmation': 0.5,  # 0.5 = 50% der Kerze muss verstrichen sein
    # UT Bot Alerts Parameter
    'ut_key_value': 1,
    'ut_atr_period': 10,
    'ut_heiken_ashi': False,
    'trade_size_pct': 100,
}

# ... [Pfade und Authentifizierung unverändert] ...

# --- UT BOT ALERTS LOGIC ---
# ... [calculate_heikin_ashi und calculate_ut_signals unverändert] ...

# --- FETCH DATA AND CALCULATE SIGNALS ---
# Mehr Kerzen holen für Rückblick
lookback_candles = max(50, params['signal_lookback_period'] + 10)
data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], lookback_candles)
data = calculate_ut_signals(data, params)

# Verbesserte Signalerkennung
current_time = datetime.now()
signals = []

for i in range(1, min(params['signal_lookback_period'] + 1, len(data))):
    idx = -i  # Beginne bei der letzten Kerze und gehe zurück
    
    # Prüfe ob die Kerze vollständig ist oder ausreichend fortgeschritten
    candle_completion = 1.0  # Standardmäßig vollständig
    
    if i == 1:  # Nur für die aktuelle Kerze
        candle_duration = timedelta(minutes=60 if params['timeframe'] == '1h' else 15)
        candle_start = data.index[idx]
        time_elapsed = current_time - candle_start
        
        # Berechne Fertigstellungsgrad
        if time_elapsed < candle_duration:
            candle_completion = time_elapsed / candle_duration
    
    # Signal nur berücksichtigen wenn Kerze vollständig oder ausreichend fortgeschritten
    if candle_completion >= params['min_signal_confirmation']:
        if data.iloc[idx]['buy_signal']:
            signals.append(('buy', data.index[idx], data.iloc[idx]['close']))
        elif data.iloc[idx]['sell_signal']:
            signals.append(('sell', data.index[idx], data.iloc[idx]['close']))

print(f"{current_time.strftime('%H:%M:%S')}: found {len(signals)} signals in last {params['signal_lookback_period']} candles")

# Entscheidungslogik
buy_signal = False
sell_signal = False

if signals:
    # Neuestes Signal verwenden
    latest_signal = signals[-1]
    signal_type, signal_time, signal_price = latest_signal
    
    # Preisänderung seit Signal prüfen
    current_price = data.iloc[-1]['close']
    price_change = abs(current_price - signal_price) / signal_price * 100
    
    # Nur handeln wenn Preis sich nicht zu stark verändert hat
    if price_change < 2:  # Max 2% Änderung
        if signal_type == 'buy':
            buy_signal = True
        else:
            sell_signal = True
        print(f"{current_time.strftime('%H:%M:%S')}: using {signal_type} signal from {signal_time.strftime('%H:%M')} (price change: {price_change:.2f}%)")
    else:
        print(f"{current_time.strftime('%H:%M:%S')}: signal expired (price change {price_change:.2f}% > 2%)")
else:
    print(f"{current_time.strftime('%H:%M:%S')}: no valid signals found")

# ... [Rest des Codes unverändert ab CHECK OPEN POSITIONS] ...
