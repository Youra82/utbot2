# code/utilities/strategy_logic.py
import os
import sys
import numpy as np
import ta
import pandas as pd

# Erlaube den Import der 'load_data_for_backtest'-Funktion aus dem analysis-Ordner
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'analysis'))
from backtest import load_data_for_backtest

def get_lower_timeframe(timeframe):
    """Gibt einen passenden kleineren Timeframe zurück."""
    timeframe_map = {
        '1d': '4h', '6h': '1h', '4h': '1h',
        '1h': '15m', '15m': '5m', '5m': '1m'
    }
    return timeframe_map.get(timeframe, None)

def calculate_signals(data, params, start_date, end_date):
    """
    Berechnet Signale und passt den Hebel dynamisch an,
    indem es die Volatilität auf einem kleineren Timeframe prüft.
    """
    main_timeframe = params['timeframe']
    lower_timeframe = get_lower_timeframe(main_timeframe)

    # --- Haupt-Indikatoren auf dem Haupt-Timeframe ---
    data['atr'] = ta.volatility.average_true_range(data['high'], data['low'], data['close'], window=params['ut_atr_period'])
    n_loss = params['ut_key_value'] * data['atr']
    
    x_atr_trailing_stop = np.zeros(len(data))
    src = data['close']
    for i in range(len(data)):
        if i == 0: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
        else:
            if src.iloc[i] > x_atr_trailing_stop[i-1] and src.iloc[i-1] > x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = max(x_atr_trailing_stop[i-1], src.iloc[i] - n_loss.iloc[i])
            elif src.iloc[i] < x_atr_trailing_stop[i-1] and src.iloc[i-1] < x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = min(x_atr_trailing_stop[i-1], src.iloc[i] + n_loss.iloc[i])
            else:
                if src.iloc[i] > x_atr_trailing_stop[i-1]: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
                else: x_atr_trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    data['buy_signal'] = (src > data['x_atr_trailing_stop']) & (src.shift(1) <= data['x_atr_trailing_stop'].shift(1))
    data['sell_signal'] = (src < data['x_atr_trailing_stop']) & (src.shift(1) >= data['x_atr_trailing_stop'].shift(1))
    
    # --- DYNAMISCHE HEBEL-ANPASSUNG ---
    if params.get('use_dynamic_leverage', False) and lower_timeframe:
        # 1. Berechne langfristige Volatilität auf dem Haupt-Timeframe
        data['atr_sma_main'] = data['atr'].rolling(window=50, min_periods=1).mean()
        main_tf_vol_ratio = data['atr_sma_main'] / data['atr']

        # 2. Lade Daten des kleineren Timeframes
        ltf_data = load_data_for_backtest(params['symbol'], lower_timeframe, start_date, end_date, hide_messages=True)
        if ltf_data is not None and not ltf_data.empty:
            ltf_data['atr_ltf'] = ta.volatility.average_true_range(ltf_data['high'], ltf_data['low'], ltf_data['close'], window=params['ut_atr_period'])
            ltf_data['atr_sma_ltf'] = ltf_data['atr_ltf'].rolling(window=50, min_periods=1).mean()
            
            # 3. Verbinde die beiden Zeitreihen
            # Für jede Kerze im Haupt-Chart finden wir die zeitlich nächste Kerze im kleinen Chart
            merged_data = pd.merge_asof(data.sort_index(), ltf_data[['atr_ltf', 'atr_sma_ltf']].sort_index(), left_index=True, right_index=True, direction='nearest')
            
            # 4. Berechne den "Nervositäts-Faktor" des kleinen Timeframes
            ltf_volatility_factor = merged_data['atr_ltf'] / merged_data['atr_sma_ltf']
            ltf_volatility_factor.fillna(1.0, inplace=True)

            # Hebe den Faktor an, um stärker auf Volatilitäts-Spikes zu reagieren
            sensitivity = params.get('ltf_vol_sensitivity', 1.0)
            ltf_volatility_factor = ltf_volatility_factor.clip(lower=1.0) ** sensitivity
            
            # 5. Finale Hebel-Berechnung
            base_lev, min_lev, max_lev = params.get('base_leverage', 5), params.get('min_leverage', 1), params.get('max_leverage', 10)
            calculated_leverage = (base_lev * main_tf_vol_ratio) / ltf_volatility_factor
            data['leverage'] = calculated_leverage.clip(lower=min_lev, upper=max_lev).round()
        else:
            # Fallback, wenn LFT-Daten nicht verfügbar sind
            data['leverage'] = params.get('leverage', 1.0)
    else:
        data['leverage'] = params.get('leverage', 1.0)

    return data
