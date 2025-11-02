import pandas as pd
import pandas_ta as ta

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet alle benötigten technischen Indikatoren.
    Erwartet ein DataFrame mit Spalten: open, high, low, close, volume.
    """

    # Stochastic
    stoch = ta.stoch(df['high'], df['low'], df['close'])
    df['stochk'] = stoch['STOCHk_14_3_3']
    df['stochd'] = stoch['STOCHd_14_3_3']

    # MACD Histogramm
    macd = ta.macd(df['close'])
    df['macd_hist'] = macd['MACDh_12_26_9']

    # Bollinger Band % Position
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bbp'] = (df['close'] - bb['BBL_20_2.0']) / (bb['BBU_20_2.0'] - bb['BBL_20_2.0'])

    # On Balance Volume
    df['obv'] = ta.obv(df['close'], df['volume'])

    # Fehlende Werte entfernen
    df = df.dropna()
    return df
