# /root/utbot2/src/utbot2/strategy/trade_logic.py
import pandas as pd
import numpy as np

def get_titan_signal(processed_data: pd.DataFrame, current_candle: pd.Series, params: dict, market_bias=None):
    """
    Vollständige Ichimoku Trading Logik für UtBot2
    
    Diese Strategie nutzt ALLE 5 Ichimoku-Komponenten für maximale Signalqualität:
    
    LONG Signal (alle Bedingungen müssen erfüllt sein):
    1. Preis über der Kumo (Wolke)
    2. Tenkan-sen über Kijun-sen (TK Cross oder bereits bullish aligned)
    3. Chikou Span über dem historischen Preis UND über der historischen Wolke
    4. Kumo ist bullish (Senkou A > Senkou B) - Zukunftswolke
    5. Preis schließt über Tenkan-sen (Momentum-Bestätigung)
    
    SHORT Signal (alle Bedingungen müssen erfüllt sein):
    1. Preis unter der Kumo (Wolke)
    2. Tenkan-sen unter Kijun-sen
    3. Chikou Span unter dem historischen Preis UND unter der historischen Wolke
    4. Kumo ist bearish (Senkou A < Senkou B)
    5. Preis schließt unter Tenkan-sen
    
    MTF-Filter: Supertrend der übergeordneten Timeframe muss mit der Richtung übereinstimmen
    """
    
    # Sicherheitscheck
    if processed_data is None or processed_data.empty or len(processed_data) < 60:
        return None, None

    # Parameter laden
    strategy_params = params.get('strategy', {})
    displacement = strategy_params.get('displacement', 26)
    require_tk_cross = strategy_params.get('require_tk_cross', False)  # Ob ein frischer Cross nötig ist
    
    # Mindestens 2 Zeilen für Crossover-Erkennung
    if len(processed_data) < displacement + 2:
        return None, None
    
    # Wir brauchen die letzten beiden abgeschlossenen Zeilen
    last_row = processed_data.iloc[-1]
    prev_row = processed_data.iloc[-2]
    
    # Aktuelle Werte
    close = last_row['close']
    high = last_row['high']
    low = last_row['low']
    tenkan = last_row['tenkan_sen']
    kijun = last_row['kijun_sen']
    
    # Die Wolke (Senkou A/B) - aktuell (für Preis-Position)
    ssa = last_row['senkou_span_a']
    ssb = last_row['senkou_span_b']
    
    # Vorherige Werte (für Crossover Erkennung)
    prev_tenkan = prev_row['tenkan_sen']
    prev_kijun = prev_row['kijun_sen']
    
    # --- Prüfung auf Gültigkeit der Indikatoren ---
    if pd.isna(ssa) or pd.isna(ssb) or pd.isna(tenkan) or pd.isna(kijun):
        return None, None
    
    signal_side = None
    signal_price = close
    
    # === Kumo (Wolke) Berechnung ===
    cloud_top = max(ssa, ssb)
    cloud_bottom = min(ssa, ssb)
    kumo_is_bullish = ssa > ssb  # Grüne Wolke
    kumo_is_bearish = ssa < ssb  # Rote Wolke
    
    # === Preis-Position zur Wolke ===
    price_above_cloud = close > cloud_top
    price_below_cloud = close < cloud_bottom
    
    # === Tenkan/Kijun Beziehung ===
    tk_bullish = tenkan > kijun
    tk_bearish = tenkan < kijun
    
    # Optional: Frischer TK Cross
    tk_cross_bull = (prev_tenkan <= prev_kijun) and (tenkan > kijun)
    tk_cross_bear = (prev_tenkan >= prev_kijun) and (tenkan < kijun)
    
    # === Chikou Span Analyse (WICHTIG für vollständiges Ichimoku) ===
    chikou_clear_bull = False
    chikou_clear_bear = False
    
    # Chikou Span ist der Close-Preis, 26 Perioden zurückversetzt
    # Wir müssen prüfen, ob der aktuelle Close über/unter dem historischen Preis
    # UND über/unter der historischen Wolke liegt
    chikou_idx = -(displacement + 1)
    if abs(chikou_idx) <= len(processed_data):
        historical_candle = processed_data.iloc[chikou_idx]
        hist_close = historical_candle['close']
        hist_high = historical_candle['high']
        hist_low = historical_candle['low']
        hist_ssa = historical_candle.get('senkou_span_a')
        hist_ssb = historical_candle.get('senkou_span_b')
        
        if not pd.isna(hist_ssa) and not pd.isna(hist_ssb):
            hist_cloud_top = max(hist_ssa, hist_ssb)
            hist_cloud_bottom = min(hist_ssa, hist_ssb)
            
            # Bullish Chikou: Close (als Chikou) ist über historischem Preis UND über historischer Wolke
            chikou_clear_bull = (close > hist_high) and (close > hist_cloud_top)
            
            # Bearish Chikou: Close (als Chikou) ist unter historischem Preis UND unter historischer Wolke
            chikou_clear_bear = (close < hist_low) and (close < hist_cloud_bottom)
    
    # === Momentum-Bestätigung ===
    price_above_tenkan = close > tenkan
    price_below_tenkan = close < tenkan
    
    # === Zukunftswolke prüfen (Kumo Twist) ===
    # Die zukünftige Wolke zeigt uns wohin der Markt tendiert
    future_kumo_bullish = kumo_is_bullish  # Bereits im aktuellen Span berechnet
    future_kumo_bearish = kumo_is_bearish
    
    # ============================================================
    # VOLLSTÄNDIGES ICHIMOKU LONG SIGNAL
    # ============================================================
    long_conditions = [
        price_above_cloud,      # 1. Preis über Kumo
        tk_bullish,             # 2. Tenkan > Kijun
        chikou_clear_bull,      # 3. Chikou über hist. Preis + hist. Wolke
        future_kumo_bullish,    # 4. Zukunftswolke ist bullish
        price_above_tenkan,     # 5. Momentum-Bestätigung
    ]
    
    # Optional: Frischer TK Cross erforderlich
    if require_tk_cross:
        long_conditions.append(tk_cross_bull)
    
    if all(long_conditions):
        signal_side = "buy"
    
    # ============================================================
    # VOLLSTÄNDIGES ICHIMOKU SHORT SIGNAL
    # ============================================================
    short_conditions = [
        price_below_cloud,      # 1. Preis unter Kumo
        tk_bearish,             # 2. Tenkan < Kijun
        chikou_clear_bear,      # 3. Chikou unter hist. Preis + hist. Wolke
        future_kumo_bearish,    # 4. Zukunftswolke ist bearish
        price_below_tenkan,     # 5. Momentum-Bestätigung
    ]
    
    # Optional: Frischer TK Cross erforderlich
    if require_tk_cross:
        short_conditions.append(tk_cross_bear)
    
    if all(short_conditions):
        signal_side = "sell"
    
    # ============================================================
    # SUPERTREND MTF FILTER
    # ============================================================
    # market_bias kommt jetzt vom Supertrend der übergeordneten Timeframe
    if signal_side and market_bias and market_bias != "NEUTRAL":
        if market_bias == "BULLISH" and signal_side == "sell":
            return None, None  # Short gegen HTF Supertrend Trend
        if market_bias == "BEARISH" and signal_side == "buy":
            return None, None  # Long gegen HTF Supertrend Trend
    
    if signal_side:
        return signal_side, signal_price

    return None, None
