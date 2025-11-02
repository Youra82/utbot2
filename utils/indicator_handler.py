# utils/indicator_handler.py (VOLLSTÄNDIG KORRIGIERT)
import pandas as pd
import pandas_ta as ta


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet Stoch, MACD Histogram, Bollinger Band Position (BBP) und OBV.
    Funktioniert robust mit allen pandas_ta Versionen.
    """

    # --- STOCH ---
    stoch = ta.stoch(df['high'], df['low'], df['close'])
    df['stochk'] = stoch.iloc[:, 0]
    df['stochd'] = stoch.iloc[:, 1]

    # --- MACD HIST ---
    macd = ta.macd(df['close'])
    df['macd_hist'] = macd.iloc[:, 2]

    # --- BOLLINGER BANDS ---
    bb = ta.bbands(df['close'], length=20, std=2)

    # Spalten dynamisch finden (für volle Kompatibilität)
    lower = bb.filter(like="BBL").iloc[:, 0]
    upper = bb.filter(like="BBU").iloc[:, 0]

    # BBP = relative Position innerhalb der Bänder (0 = unteres Band, 1 = oberes Band)
    df['bbp'] = (df['close'] - lower) / (upper - lower)

    # --- OBV ---
    df['obv'] = ta.obv(df['close'], df['volume'])

    # NaN entfernen
    df = df.dropna()

    return df
