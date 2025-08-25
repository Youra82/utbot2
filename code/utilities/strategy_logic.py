# code/utilities/strategy_logic.py
import numpy as np
import ta
import pandas as pd

def get_lower_timeframe(timeframe):
    """Gibt einen passenden kleineren Timeframe zurück."""
    timeframe_map = {
        '1d': '4h', '6h': '1h', '4h': '1h',
        '1h': '15m', '15m': '5m', '5m': '1m'
    }
    return timeframe_map.get(timeframe)

def calculate_signals(data, params, ltf_data=None):
    """
    Berechnet Signale und den dynamischen Hebel. Bekommt ALLE Daten als Input.
    """
    # Haupt-Indikatoren auf dem Haupt-Timeframe
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
    
    # DYNAMISCHE HEBEL-ANPASSUNG
    if params.get('use_dynamic_leverage', False):
        base_lev = params.get('base_leverage', 5)
        min_lev = params.get('min_leverage', 1)
        max_lev = params.get('max_leverage', 10)

        data['atr_sma_main'] = data['atr'].rolling(window=50, min_periods=1).mean()
        main_tf_vol_ratio = data['atr_sma_main'] / data['atr']
        
        ltf_volatility_factor = pd.Series(1.0, index=data.index)
        if ltf_data is not None and not ltf_data.empty:
            ltf_data['atr_ltf'] = ta.volatility.average_true_range(ltf_data['high'], ltf_data['low'], ltf_data['close'], window=params['ut_atr_period'])
            ltf_data['atr_sma_ltf'] = ltf_data['atr_ltf'].rolling(window=50, min_periods=1).mean()
            
            merged_data = pd.merge_asof(data.sort_index(), ltf_data[['atr_ltf', 'atr_sma_ltf']].sort_index(), left_index=True, right_index=True, direction='nearest')
            ltf_vol_ratio = merged_data['atr_ltf'] / merged_data['atr_sma_ltf']
            ltf_volatility_factor = ltf_vol_ratio.fillna(1.0)

        sensitivity = params.get('ltf_vol_sensitivity', 1.0)
        final_ltf_factor = ltf_volatility_factor.clip(lower=1.0) ** sensitivity
        
        calculated_leverage = (base_lev * main_tf_vol_ratio) / final_ltf_factor
        data['leverage'] = calculated_leverage.clip(lower=min_lev, upper=max_lev)
        data['leverage'].fillna(base_lev, inplace=True)
        data['leverage'] = data['leverage'].round()
    else:
        data['leverage'] = params.get('leverage', 1.0)

    return data
