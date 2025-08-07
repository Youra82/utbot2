import os
import sys
import json
import time
import pandas as pd
import ta
from datetime import datetime, timedelta
from utilities.bitget_futures import BitgetFutures  # Vorhandene Utility-Klasse

class Strategy:
    def __init__(self, params, symbol, timeframe, leverage):
        self.params = params
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        
        # API Setup mit vorhandener secret.json
        key_path = os.path.join(os.path.dirname(__file__), '../../../secret.json')
        with open(key_path, "r") as f:
            api_setup = json.load(f)[self.params['key_name']]
        self.exchange = BitgetFutures(api_setup)
        
        # Live-Trading Variablen
        self.position_open = False
        self.position_side = None
        self.position_size = 0
        self.trailing_stop = 0.0
        self.atr = 0.0
        
        # Standardparameter
        self.params.setdefault('a', 1)         # Key Value (Sensitivität)
        self.params.setdefault('c', 10)        # ATR Periode
        self.params.setdefault('use_heikin_ashi', False)
        self.set_trade_mode()
        
        # Exchange Einstellungen und Initialdaten
        self.set_exchange_settings()
        self.data = self.fetch_initial_data()
        self.populate_indicators()

    # --- Trade Mode ---
    def set_trade_mode(self):
        self.params.setdefault("mode", "both")
        valid_modes = ("long", "short", "both")
        if self.params["mode"] not in valid_modes:
            raise ValueError(f"Ungültiger Modus. Erlaubt: {', '.join(valid_modes)}")

        self.ignore_shorts = self.params["mode"] == "long"
        self.ignore_longs = self.params["mode"] == "short"
    
    # --- Exchange Setup ---
    def set_exchange_settings(self):
        """Setzt Hebel und Margin-Modus"""
        try:
            self.exchange.set_margin_mode(self.symbol, self.params['margin_mode'])
            self.exchange.set_leverage(
                self.symbol, 
                self.params['margin_mode'], 
                self.leverage
            )
            print(f"Hebel auf {self.leverage}x gesetzt ({self.params['margin_mode']} Margin)")
        except Exception as e:
            print(f"Fehler bei Exchange-Einstellungen: {e}")
    
    # --- Datenbeschaffung ---
    def fetch_initial_data(self, limit=100):
        """Lädt initiale OHLCV-Daten"""
        print(f"Lade historische Daten für {self.symbol} ({self.timeframe})...")
        df = self.exchange.fetch_recent_ohlcv(
            self.symbol, 
            self.timeframe, 
            limit
        )
        print(f"{len(df)} Kerzen geladen")
        return df
    
    def fetch_new_data(self):
        """Holt neue Marktdaten"""
        new_df = self.exchange.fetch_recent_ohlcv(
            self.symbol, 
            self.timeframe, 
            limit=2
        )
        if not new_df.empty:
            last_timestamp = self.data.index[-1]
            new_data = new_df[new_df.index > last_timestamp]
            
            if not new_data.empty:
                self.data = pd.concat([self.data, new_data])
                self.populate_indicators()
                return True
        return False
    
    # --- Indikatorberechnung (Original-Logik) ---
    def calculate_heikin_ashi(self):
        """Berechnet Heikin-Ashi Kerzen"""
        ha_close = (self.data['open'] + self.data['high'] + 
                    self.data['low'] + self.data['close']) / 4
        
        ha_open = self.data['open'].copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([self.data['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([self.data['low'], ha_open, ha_close], axis=1).min(axis=1)
        
        return ha_open, ha_high, ha_low, ha_close
        
    def populate_indicators(self):
        """Berechnet alle Indikatoren (Original-Logik)"""
        if self.params['use_heikin_ashi']:
            ha_open, ha_high, ha_low, ha_close = self.calculate_heikin_ashi()
            src = ha_close
        else:
            src = self.data['close']
        
        atr_period = self.params['c']
        self.data['atr'] = ta.volatility.average_true_range(
            self.data['high'], self.data['low'], self.data['close'], window=atr_period
        )
        
        nLoss = self.params['a'] * self.data['atr']
        trailing_stop = pd.Series(0.0, index=self.data.index)
        trailing_stop.iloc[0] = src.iloc[0] - nLoss.iloc[0] if src.iloc[0] > 0 else src.iloc[0] + nLoss.iloc[0]
        
        for i in range(1, len(self.data)):
            prev_stop = trailing_stop.iloc[i-1]
            current_src = src.iloc[i]
            prev_src = src.iloc[i-1]
            
            if current_src > prev_stop and prev_src > prev_stop:
                trailing_stop.iloc[i] = max(prev_stop, current_src - nLoss.iloc[i])
            elif current_src < prev_stop and prev_src < prev_stop:
                trailing_stop.iloc[i] = min(prev_stop, current_src + nLoss.iloc[i])
            else:
                if current_src > prev_stop:
                    trailing_stop.iloc[i] = current_src - nLoss.iloc[i]
                else:
                    trailing_stop.iloc[i] = current_src + nLoss.iloc[i]
        
        self.data['trailing_stop'] = trailing_stop
        self.data['buy_signal'] = (src > trailing_stop) & (src.shift(1) <= trailing_stop.shift(1))
        self.data['sell_signal'] = (src < trailing_stop) & (src.shift(1) >= trailing_stop.shift(1))
        
        # Aktuelle Werte speichern
        self.atr = self.data['atr'].iloc[-1]
        self.trailing_stop = trailing_stop.iloc[-1]
    
    # --- Live-Trading Funktionen ---
    def calculate_position_size(self):
        """Berechnet Positionsgröße basierend auf Kontostand"""
        balance = self.exchange.fetch_balance()['USDT']['free']
        
        if 'position_size_percentage' in self.params:
            return balance * self.params['position_size_percentage'] / 100
        elif 'position_size_fixed_amount' in self.params:
            return self.params['position_size_fixed_amount']
        else:
            return balance * 0.1  # Default: 10% des Kontos
    
    def open_position(self, side):
        """Öffnet eine Live-Position"""
        try:
            position_size = self.calculate_position_size()
            current_price = self.data['close'].iloc[-1]
            amount = position_size / current_price
            amount = self.exchange.amount_to_precision(self.symbol, amount)
            
            if side == 'long':
                order = self.exchange.place_market_order(self.symbol, 'buy', amount)
            else:
                order = self.exchange.place_market_order(self.symbol, 'sell', amount)
            
            print(f"{side.capitalize()}-Position eröffnet: {amount} {self.symbol}")
            self.position_open = True
            self.position_side = side
            self.position_size = amount
        except Exception as e:
            print(f"Fehler beim Öffnen der Position: {e}")
    
    def close_position(self):
        """Schließt eine Live-Position"""
        try:
            if self.position_side == 'long':
                self.exchange.place_market_order(self.symbol, 'sell', self.position_size, reduce=True)
            else:
                self.exchange.place_market_order(self.symbol, 'buy', self.position_size, reduce=True)
            
            print(f"Position geschlossen: {self.position_size} {self.symbol}")
            self.position_open = False
            self.position_side = None
            self.position_size = 0
        except Exception as e:
            print(f"Fehler beim Schließen der Position: {e}")
    
    def check_signals(self):
        """Prüft Signale und führt Handelsaktionen aus"""
        last_row = self.data.iloc[-1]
        
        # Position schließen bei gegenteiligem Signal
        if self.position_open:
            if (self.position_side == 'long' and last_row['sell_signal']) or \
               (self.position_side == 'short' and last_row['buy_signal']):
                self.close_position()
        
        # Neue Position eröffnen
        if not self.position_open:
            if not self.ignore_longs and last_row['buy_signal']:
                self.open_position('long')
            elif not self.ignore_shorts and last_row['sell_signal']:
                self.open_position('short')
    
    def check_stop_loss(self):
        """Prüft ob Trailing-Stop erreicht wurde"""
        if not self.position_open:
            return False
        
        current_price = self.data['close'].iloc[-1]
        
        if self.position_side == 'long' and current_price <= self.trailing_stop:
            print(f"Trailing-Stop erreicht! ({current_price} <= {self.trailing_stop})")
            self.close_position()
            return True
        elif self.position_side == 'short' and current_price >= self.trailing_stop:
            print(f"Trailing-Stop erreicht! ({current_price} >= {self.trailing_stop})")
            self.close_position()
            return True
        return False
    
    def update_trailing_stop(self):
        """Aktualisiert den Trailing-Stop für offene Positionen"""
        if not self.position_open:
            return
        
        current_price = self.data['close'].iloc[-1]
        nLoss = self.params['a'] * self.atr
        
        if self.position_side == 'long':
            new_stop = max(self.trailing_stop, current_price - nLoss)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
                print(f"Neuer Trailing-Stop (Long): {self.trailing_stop:.2f}")
        else:
            new_stop = min(self.trailing_stop, current_price + nLoss)
            if new_stop < self.trailing_stop:
                self.trailing_stop = new_stop
                print(f"Neuer Trailing-Stop (Short): {self.trailing_stop:.2f}")
    
    def run_live(self):
        """Hauptfunktion für Live-Trading"""
        print(f"Starte Live-Trading für {self.symbol} (TF: {self.timeframe}, Hebel: {self.leverage}x)")
        
        while True:
            try:
                if self.fetch_new_data():
                    self.update_trailing_stop()
                    
                    if not self.check_stop_loss():
                        self.check_signals()
                
                sleep_time = self.calculate_sleep_time()
                print(f"Nächste Aktualisierung in {sleep_time:.1f}s")
                time.sleep(sleep_time)
                
            except Exception as e:
                print(f"Fehler im Hauptloop: {e}")
                time.sleep(60)
    
    def calculate_sleep_time(self):
        """Berechnet Wartezeit bis zur nächsten Kerze"""
        now = datetime.utcnow()
        
        if self.timeframe.endswith('m'):
            minutes = int(self.timeframe[:-1])
            next_candle = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes)
        elif self.timeframe.endswith('h'):
            hours = int(self.timeframe[:-1])
            next_candle = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours)
        else:  # Tägliche Kerzen
            next_candle = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        return max(10, (next_candle - now).total_seconds())

if __name__ == "__main__":
    # HIER KONFIGURATION ÄNDERN
    PARAMS = {
        'key_name': 'envelope',          # Muss in secret.json existieren
        'margin_mode': 'isolated',        # Margin-Modus
        'mode': 'both',                   # Handelsrichtung
        'a': 1.5,                         # ATR Multiplikator
        'c': 14,                          # ATR Periode
        'use_heikin_ashi': True,          # Heikin-Ashi verwenden
        'position_size_percentage': 15    # Risiko pro Trade in %
    }
    
    SYMBOL = "BTC/USDT:USDT"      # Handelscoin
    TIMEFRAME = "15m"             # Zeitrahmen
    LEVERAGE = 10                 # Hebel
    
    # Starte Live-Trading
    bot = Strategy(PARAMS, SYMBOL, TIMEFRAME, LEVERAGE)
    bot.run_live()
