import pandas as pd
import ta
from . import tools as ut

class Strategy:
    def __init__(self, params, ohlcv) -> None:
        self.params = params
        self.data = ohlcv.copy()
        
        # Standardparameter
        self.params.setdefault('a', 1)         # Key Value (Sensitivität)
        self.params.setdefault('c', 10)        # ATR Periode
        self.params.setdefault('use_heikin_ashi', False)  # Heikin Ashi verwenden
        
        self.populate_indicators()
        self.set_trade_mode()
        
    def set_trade_mode(self):
        self.params.setdefault("mode", "both")
        valid_modes = ("long", "short", "both")
        if self.params["mode"] not in valid_modes:
            raise ValueError(f"Wrong strategy mode. Can be {', '.join(valid_modes)}.")

        self.ignore_shorts = self.params["mode"] == "long"
        self.ignore_longs = self.params["mode"] == "short"
        
    def calculate_heikin_ashi(self):
        """Berechnet Heikin-Ashi Kerzen aus den OHLC-Daten"""
        ha_close = (self.data['open'] + self.data['high'] + self.data['low'] + self.data['close']) / 4
        
        ha_open = self.data['open'].copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([self.data['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([self.data['low'], ha_open, ha_close], axis=1).min(axis=1)
        
        return ha_open, ha_high, ha_low, ha_close
        
    def populate_indicators(self):
        """Berechnet alle Indikatoren für die Strategie"""
        # Heikin-Ashi Kerzen berechnen falls aktiviert
        if self.params['use_heikin_ashi']:
            ha_open, ha_high, ha_low, ha_close = self.calculate_heikin_ashi()
            src = ha_close
        else:
            src = self.data['close']
        
        # ATR berechnen
        atr_period = self.params['c']
        self.data['atr'] = ta.volatility.average_true_range(
            self.data['high'], self.data['low'], self.data['close'], window=atr_period
        )
        
        # Trailing Stop Loss berechnen
        nLoss = self.params['a'] * self.data['atr']
        trailing_stop = pd.Series(0.0, index=self.data.index)
        
        # Initialer Wert
        trailing_stop.iloc[0] = src.iloc[0] - nLoss.iloc[0] if src.iloc[0] > 0 else src.iloc[0] + nLoss.iloc[0]
        
        # Trailing Stop berechnen (rekursive Logik)
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
        
        # Signale generieren
        self.data['buy_signal'] = (src > trailing_stop) & (src.shift(1) <= trailing_stop.shift(1))
        self.data['sell_signal'] = (src < trailing_stop) & (src.shift(1) >= trailing_stop.shift(1))
        
    def evaluate_orders(self, time, row):
        """Bewertet Handelsentscheidungen für jeden Zeitschritt"""
        # Long-Position eröffnen
        if not self.ignore_longs and row['buy_signal']:
            if self.position.side == 'short':
                self.close_trade(time, row['open'], "Close short for long")
            
            if 'position_size_percentage' in self.params:
                initial_margin = self.balance * self.params['position_size_percentage'] / 100
            elif 'position_size_fixed_amount' in self.params:
                initial_margin = self.params['position_size_fixed_amount']
            
            self.balance -= initial_margin
            self.position.open(
                time, 
                'long', 
                initial_margin, 
                row['open'], 
                "UT Long Entry"
            )
        
        # Short-Position eröffnen
        elif not self.ignore_shorts and row['sell_signal']:
            if self.position.side == 'long':
                self.close_trade(time, row['open'], "Close long for short")
            
            if 'position_size_percentage' in self.params:
                initial_margin = self.balance * self.params['position_size_percentage'] / 100
            elif 'position_size_fixed_amount' in self.params:
                initial_margin = self.params['position_size_fixed_amount']
            
            self.balance -= initial_margin
            self.position.open(
                time, 
                'short', 
                initial_margin, 
                row['open'], 
                "UT Short Entry"
            )
    
    def close_trade(self, time, price, reason):
        """Schließt eine offene Position"""
        self.position.close(time, price, reason)
        open_balance = self.balance
        self.balance += self.position.initial_margin + self.position.net_pnl
        trade_info = self.position.info()
        trade_info["open_balance"] = open_balance
        trade_info["close_balance"] = self.balance
        self.trades_info.append(trade_info)
    
    def run_backtest(self, initial_balance, leverage, fee_rate=0.0006):
        """Führt den Backtest durch"""
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.position = ut.Position(leverage=leverage, fee_rate=fee_rate)
        self.equity_update_interval = pd.Timedelta(hours=6)
        self.previous_equity_update_time = pd.Timestamp('1900-01-01')
        self.trades_info = []
        self.equity_record = []

        for time, row in self.data.iterrows():
            self.evaluate_orders(time, row)
            self.previous_equity_update_time = ut.update_equity_record(
                time,
                self.position,
                self.balance,
                row["close"],
                self.previous_equity_update_time,
                self.equity_update_interval,
                self.equity_record
            )

        self.trades_info = pd.DataFrame(self.trades_info)
        self.equity_record = pd.DataFrame(self.equity_record).set_index("time")
        self.final_equity = round(self.equity_record.iloc[-1]["equity"], 2)
    
    def save_equity_record(self, path):
        self.equity_record.to_csv(path + '_equity_record.csv', header=True, index=True)
    
    def save_trades_info(self, path):
        self.trades_info.to_csv(path + '_trades_info.csv', header=True, index=True)