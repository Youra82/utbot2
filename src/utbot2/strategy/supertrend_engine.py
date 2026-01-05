# /root/utbot2/src/utbot2/strategy/supertrend_engine.py
import pandas as pd
import numpy as np


class SupertrendEngine:
    """
    Berechnet den Supertrend-Indikator für Multi-Timeframe-Filtering.
    
    Der Supertrend kombiniert ATR mit einem Multiplikator, um dynamische
    Support/Resistance-Levels zu berechnen.
    
    Formel:
    - Basic Upper Band = (High + Low) / 2 + (Multiplier × ATR)
    - Basic Lower Band = (High + Low) / 2 - (Multiplier × ATR)
    - Supertrend wechselt zwischen Upper/Lower Band basierend auf Preis-Breaks
    """
    
    def __init__(self, settings: dict = None):
        settings = settings or {}
        self.atr_period = settings.get('supertrend_atr_period', 10)
        self.multiplier = settings.get('supertrend_multiplier', 3.0)
    
    def _calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """Berechnet den Average True Range (ATR)."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range berechnen
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR als Rolling Mean des True Range
        atr = true_range.rolling(window=self.atr_period).mean()
        
        return atr
    
    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fügt Supertrend-Spalten zum DataFrame hinzu.
        
        Neue Spalten:
        - supertrend: Der Supertrend-Wert
        - supertrend_direction: 1 = Bullish (Preis über Supertrend), -1 = Bearish
        - supertrend_upper: Upper Band
        - supertrend_lower: Lower Band
        """
        if df.empty or len(df) < self.atr_period + 1:
            return df
        
        df = df.copy()
        
        # ATR berechnen
        atr = self._calculate_atr(df)
        
        # Median Price (HL2)
        hl2 = (df['high'] + df['low']) / 2
        
        # Basic Bands berechnen
        basic_upper = hl2 + (self.multiplier * atr)
        basic_lower = hl2 - (self.multiplier * atr)
        
        # Initialisiere Supertrend-Arrays
        n = len(df)
        supertrend = np.zeros(n)
        direction = np.zeros(n)
        final_upper = np.zeros(n)
        final_lower = np.zeros(n)
        
        close = df['close'].values
        
        # Initialisierung
        final_upper[self.atr_period] = basic_upper.iloc[self.atr_period]
        final_lower[self.atr_period] = basic_lower.iloc[self.atr_period]
        supertrend[self.atr_period] = final_upper[self.atr_period]
        direction[self.atr_period] = -1  # Start bearish
        
        # Supertrend-Berechnung
        for i in range(self.atr_period + 1, n):
            # Upper Band: Nimm das Minimum, wenn Close > vorheriges Upper
            if basic_upper.iloc[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
                final_upper[i] = basic_upper.iloc[i]
            else:
                final_upper[i] = final_upper[i-1]
            
            # Lower Band: Nimm das Maximum, wenn Close < vorheriges Lower
            if basic_lower.iloc[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
                final_lower[i] = basic_lower.iloc[i]
            else:
                final_lower[i] = final_lower[i-1]
            
            # Supertrend-Richtung bestimmen
            if direction[i-1] == -1:  # War bearish
                if close[i] > final_upper[i]:
                    direction[i] = 1  # Wechsel zu bullish
                    supertrend[i] = final_lower[i]
                else:
                    direction[i] = -1
                    supertrend[i] = final_upper[i]
            else:  # War bullish
                if close[i] < final_lower[i]:
                    direction[i] = -1  # Wechsel zu bearish
                    supertrend[i] = final_upper[i]
                else:
                    direction[i] = 1
                    supertrend[i] = final_lower[i]
        
        df['supertrend'] = supertrend
        df['supertrend_direction'] = direction
        df['supertrend_upper'] = final_upper
        df['supertrend_lower'] = final_lower
        
        # Ersetze initiale Nullen mit NaN für Konsistenz
        df.loc[df.index[:self.atr_period], ['supertrend', 'supertrend_direction', 
                                             'supertrend_upper', 'supertrend_lower']] = np.nan
        
        return df
    
    def get_trend(self, df: pd.DataFrame) -> str:
        """
        Gibt den aktuellen Trend basierend auf Supertrend zurück.
        
        Returns:
            "BULLISH" - Preis über Supertrend
            "BEARISH" - Preis unter Supertrend
            "NEUTRAL" - Keine klare Richtung / nicht genug Daten
        """
        if df.empty or 'supertrend_direction' not in df.columns:
            return "NEUTRAL"
        
        last_direction = df['supertrend_direction'].iloc[-1]
        
        if pd.isna(last_direction):
            return "NEUTRAL"
        
        if last_direction == 1:
            return "BULLISH"
        elif last_direction == -1:
            return "BEARISH"
        else:
            return "NEUTRAL"
