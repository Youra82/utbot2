# /root/utbot2/src/utbot2/strategy/trade_logic.py
import pandas as pd
import numpy as np

def get_titan_signal(processed_data: pd.DataFrame, current_candle: pd.Series, params: dict, market_bias=None):
    """
    Ichimoku Trading Logik für UtBot2 - ERWEITERTE VERSION
    
    Strategie:
    1. TK Cross (Tenkan kreuzt Kijun) mit Mindestabstand
    2. Wolken-Validierung: Dicke und Qualität der Wolke
    3. TK-Lines müssen beide auf richtiger Seite der Wolke sein
    4. Verbesserter Chikou Filter: Freier Raum in historischer Wolke
    5. ADX Filter: Nur bei Trends traden (ADX > 25)
    6. Volume Confirmation: Überdurchschnittliches Volumen
    """
    
    # Sicherheitscheck
    if processed_data is None or processed_data.empty or len(processed_data) < 30:
        return None, None

    # Parameter laden
    strategy_params = params.get('strategy', {})
    use_chikou_filter = strategy_params.get('use_chikou_filter', True)
    displacement = strategy_params.get('displacement', 26)
    
    # Trading Filter Einstellungen
    min_tk_separation_pct = strategy_params.get('min_tk_separation_pct', 0.3)  # 0.3% Mindestabstand
    min_cloud_thickness_pct = strategy_params.get('min_cloud_thickness_pct', 0.5)  # 0.5% Wolkendicke
    min_adx = strategy_params.get('min_adx', 25)  # ADX Minimum für Trend
    min_volume_multiplier = strategy_params.get('min_volume_multiplier', 1.2)  # 20% über Durchschnitt
    
    # Wir brauchen die letzten beiden abgeschlossenen Zeilen für Crossovers
    last_row = processed_data.iloc[-1]
    prev_row = processed_data.iloc[-2]
    
    # Aktuelle Werte
    close = last_row['close']
    tenkan = last_row['tenkan_sen']
    kijun = last_row['kijun_sen']
    
    # Die Wolke (Senkou A/B) ist bereits geshiftet im DataFrame.
    ssa = last_row['senkou_span_a']
    ssb = last_row['senkou_span_b']
    
    # Vorherige Werte (für Crossover Erkennung)
    prev_tenkan = prev_row['tenkan_sen']
    prev_kijun = prev_row['kijun_sen']
    
    signal_side = None
    signal_price = close
    
    # --- Prüfung auf Gültigkeit der Indikatoren ---
    if pd.isna(ssa) or pd.isna(ssb) or pd.isna(tenkan) or pd.isna(kijun):
        return None, None

    # --- FILTER 1: Wolken-Validierung ---
    # Wolke muss dick genug sein (mindestens 0.5% des Preises)
    cloud_thickness = abs(ssa - ssb) / close
    if cloud_thickness < (min_cloud_thickness_pct / 100.0):
        return None, None  # Wolke zu dünn = unsicheres Signal

    # --- FILTER 2: ADX Filter (nur bei Trends traden) ---
    if 'adx' in last_row and not pd.isna(last_row['adx']):
        current_adx = last_row['adx']
        if current_adx < min_adx:
            return None, None  # ADX zu niedrig = Ranging-Markt

    # --- FILTER 3: Volume Confirmation ---
    if 'volume' in processed_data.columns and len(processed_data) > 20:
        avg_volume = processed_data['volume'].rolling(20).mean().iloc[-1]
        current_volume = last_row['volume']
        if not pd.isna(avg_volume) and avg_volume > 0:
            if current_volume < avg_volume * min_volume_multiplier:
                return None, None  # Volume zu niedrig = schwaches Signal

    # --- LONG SIGNAL ---
    # 1. TK Cross Bullish: Tenkan kreuzt Kijun von unten nach oben
    tk_cross_bull = (prev_tenkan <= prev_kijun) and (tenkan > kijun)
    
    # 2. TK Separation Check: Mindestabstand zwischen den Linien
    tk_separation_pct = abs(tenkan - kijun) / close * 100
    
    # 3. Kumo Filter: Preis muss ÜBER der Wolke sein
    cloud_top = max(ssa, ssb)
    cloud_bottom = min(ssa, ssb)
    price_above_cloud = close > cloud_top
    
    # 4. TK Lines müssen beide über der Wolke sein (stärkeres Signal)
    tk_above_cloud = tenkan > cloud_top and kijun > cloud_top
    
    if tk_cross_bull and price_above_cloud and tk_above_cloud and tk_separation_pct >= min_tk_separation_pct:
        signal_side = "buy"
        
    # --- SHORT SIGNAL ---
    # 1. TK Cross Bearish: Tenkan kreuzt Kijun von oben nach unten
    tk_cross_bear = (prev_tenkan >= prev_kijun) and (tenkan < kijun)
    
    # 2. Kumo Filter: Preis muss UNTER der Wolke sein
    price_below_cloud = close < cloud_bottom
    
    # 3. TK Lines müssen beide unter der Wolke sein (stärkeres Signal)
    tk_below_cloud = tenkan < cloud_bottom and kijun < cloud_bottom
    
    if tk_cross_bear and price_below_cloud and tk_below_cloud and tk_separation_pct >= min_tk_separation_pct:
        signal_side = "sell"

    # --- Chikou Span Filter (Verbessert) ---
    if signal_side and use_chikou_filter:
        if len(processed_data) > displacement + 1:
            # Prüfe historische Wolke (wo Chikou jetzt ist)
            chikou_idx = -(displacement + 1)
            if abs(chikou_idx) <= len(processed_data):
                historical_candle = processed_data.iloc[chikou_idx]
                hist_ssa = historical_candle.get('senkou_span_a')
                hist_ssb = historical_candle.get('senkou_span_b')
                
                if not pd.isna(hist_ssa) and not pd.isna(hist_ssb):
                    hist_cloud_top = max(hist_ssa, hist_ssb)
                    hist_cloud_bottom = min(hist_ssa, hist_ssb)
                    
                    # Chikou muss außerhalb der historischen Wolke sein
                    if signal_side == "buy" and close <= hist_cloud_top:
                        return None, None  # Chikou nicht in freiem Raum
                    if signal_side == "sell" and close >= hist_cloud_bottom:
                        return None, None  # Chikou nicht in freiem Raum
                
    # --- MTF Bias Filter ---
    if market_bias and market_bias != "NEUTRAL":
        if market_bias == "BULLISH" and signal_side == "sell":
            return None, None
        if market_bias == "BEARISH" and signal_side == "buy":
            return None, None

    if signal_side:
        return signal_side, signal_price

    return None, None
