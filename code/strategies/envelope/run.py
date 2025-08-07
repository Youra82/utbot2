import os
import sys
import json
import time
import pandas as pd
import ta
from datetime import datetime, timedelta
from utilities.bitget_futures import BitgetFutures

class LiveTrailingStopBot:
    def __init__(self, params, symbol, timeframe, leverage):
        self.params = params
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        
        # API Setup
        key_path = os.path.join(os.path.dirname(__file__), '../../../secret.json')
        with open(key_path, "r") as f:
            api_setup = json.load(f)[self.params['key_name']]
        self.exchange = BitgetFutures(api_setup)
        
        # State variables
        self.position_open = False
        self.position_side = None
        self.position_size = 0
        self.trailing_stop = 0.0
        self.atr = 0.0
        
        # Strategy parameters
        self.params.setdefault('a', 1.0)         # ATR Multiplier
        self.params.setdefault('c', 10)           # ATR Period
        self.params.setdefault('use_heikin_ashi', False)
        self.set_trade_mode()
        
        # Initialize
        self.set_exchange_settings()
        self.data = self.fetch_initial_data()
        self.calculate_indicators()
        
    def set_trade_mode(self):
        """Set trading mode (long/short/both)"""
        valid_modes = ("long", "short", "both")
        if self.params["mode"] not in valid_modes:
            raise ValueError(f"Invalid mode. Allowed: {', '.join(valid_modes)}")

        self.ignore_shorts = self.params["mode"] == "long"
        self.ignore_longs = self.params["mode"] == "short"
    
    def set_exchange_settings(self):
        """Set leverage and margin mode"""
        try:
            self.exchange.set_margin_mode(self.symbol, self.params['margin_mode'])
            self.exchange.set_leverage(
                self.symbol, 
                self.params['margin_mode'], 
                self.leverage
            )
            print(f"Leverage set to {self.leverage}x ({self.params['margin_mode']} margin)")
        except Exception as e:
            print(f"Error setting exchange: {e}")
    
    def fetch_initial_data(self, limit=100):
        """Fetch initial OHLCV data"""
        print(f"Loading historical data for {self.symbol} ({self.timeframe})...")
        df = self.exchange.fetch_recent_ohlcv(
            self.symbol, 
            self.timeframe, 
            limit
        )
        print(f"{len(df)} candles loaded")
        return df
    
    def fetch_new_data(self):
        """Fetch new market data"""
        new_df = self.exchange.fetch_recent_ohlcv(
            self.symbol, 
            self.timeframe, 
            limit=2
        )
        if not new_df.empty:
            # Add only new data
            last_timestamp = self.data.index[-1]
            new_data = new_df[new_df.index > last_timestamp]
            
            if not new_data.empty:
                self.data = pd.concat([self.data, new_data])
                self.calculate_indicators()
                return True
        return False
    
    def calculate_heikin_ashi(self):
        """Calculate Heikin-Ashi candles"""
        ha_close = (self.data['open'] + self.data['high'] + 
                    self.data['low'] + self.data['close']) / 4
        
        ha_open = self.data['open'].copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([self.data['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([self.data['low'], ha_open, ha_close], axis=1).min(axis=1)
        
        return ha_open, ha_high, ha_low, ha_close
    
    def calculate_indicators(self):
        """Calculate indicators for the strategy"""
        # Use Heikin-Ashi if enabled
        if self.params['use_heikin_ashi']:
            ha_open, ha_high, ha_low, ha_close = self.calculate_heikin_ashi()
            src = ha_close
        else:
            src = self.data['close']
        
        # Calculate ATR
        atr_period = self.params['c']
        self.data['atr'] = ta.volatility.average_true_range(
            self.data['high'], self.data['low'], self.data['close'], 
            window=atr_period
        )
        
        # Calculate trailing stop
        nLoss = self.params['a'] * self.data['atr']
        trailing_stop = src.copy().astype(float)
        
        # Initial value
        trailing_stop.iloc[0] = src.iloc[0] - nLoss.iloc[0] if src.iloc[0] > 0 else src.iloc[0] + nLoss.iloc[0]
        
        # Calculate trailing stop
        for i in range(1, len(self.data)):
            prev_stop = trailing_stop.iloc[i-1]
            current_src = src.iloc[i]
            
            if current_src > prev_stop:
                trailing_stop.iloc[i] = max(prev_stop, current_src - nLoss.iloc[i])
            else:
                trailing_stop.iloc[i] = min(prev_stop, current_src + nLoss.iloc[i])
        
        self.data['trailing_stop'] = trailing_stop
        
        # Generate signals
        self.data['buy_signal'] = (src > trailing_stop) & (src.shift(1) <= trailing_stop.shift(1))
        self.data['sell_signal'] = (src < trailing_stop) & (src.shift(1) >= trailing_stop.shift(1))
        
        # Store current values
        self.atr = self.data['atr'].iloc[-1]
        self.trailing_stop = trailing_stop.iloc[-1]
    
    def calculate_position_size(self):
        """Calculate position size based on balance"""
        balance = self.exchange.fetch_balance()['USDT']['free']
        
        if 'position_size_percentage' in self.params:
            return balance * self.params['position_size_percentage'] / 100
        elif 'position_size_fixed_amount' in self.params:
            return self.params['position_size_fixed_amount']
        else:
            # Default: 10% of balance
            return balance * 0.1
    
    def open_position(self, side):
        """Open a position"""
        try:
            position_size = self.calculate_position_size()
            current_price = self.data['close'].iloc[-1]
            amount = position_size / current_price
            amount = self.exchange.amount_to_precision(self.symbol, amount)
            
            if side == 'long':
                order = self.exchange.place_market_order(self.symbol, 'buy', amount)
            else:
                order = self.exchange.place_market_order(self.symbol, 'sell', amount)
            
            print(f"Opened {side} position: {amount} {self.symbol} at {current_price}")
            self.position_open = True
            self.position_side = side
            self.position_size = amount
            
            return order
        except Exception as e:
            print(f"Error opening position: {e}")
            return None
    
    def close_position(self):
        """Close current position"""
        try:
            if self.position_side == 'long':
                order = self.exchange.place_market_order(self.symbol, 'sell', self.position_size, reduce=True)
            else:
                order = self.exchange.place_market_order(self.symbol, 'buy', self.position_size, reduce=True)
            
            print(f"Closed position: {self.position_size} {self.symbol}")
            self.position_open = False
            self.position_side = None
            self.position_size = 0
            
            return order
        except Exception as e:
            print(f"Error closing position: {e}")
            return None
    
    def check_signals(self):
        """Check for trading signals"""
        last_row = self.data.iloc[-1]
        current_price = last_row['close']
        
        # Close position if opposite signal
        if self.position_open:
            if (self.position_side == 'long' and last_row['sell_signal']) or \
               (self.position_side == 'short' and last_row['buy_signal']):
                self.close_position()
        
        # Open new position
        if not self.position_open:
            if not self.ignore_longs and last_row['buy_signal']:
                self.open_position('long')
            elif not self.ignore_shorts and last_row['sell_signal']:
                self.open_position('short')
    
    def update_trailing_stop(self):
        """Update trailing stop for existing position"""
        if not self.position_open:
            return
        
        current_price = self.data['close'].iloc[-1]
        nLoss = self.params['a'] * self.atr
        
        if self.position_side == 'long':
            new_stop = max(self.trailing_stop, current_price - nLoss)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
                print(f"Updated long trailing stop: {self.trailing_stop:.2f}")
        else:
            new_stop = min(self.trailing_stop, current_price + nLoss)
            if new_stop < self.trailing_stop:
                self.trailing_stop = new_stop
                print(f"Updated short trailing stop: {self.trailing_stop:.2f}")
    
    def check_stop_loss(self):
        """Check if trailing stop was hit"""
        if not self.position_open:
            return False
        
        current_price = self.data['close'].iloc[-1]
        
        if self.position_side == 'long' and current_price <= self.trailing_stop:
            print(f"Trailing stop hit for long position! ({current_price} <= {self.trailing_stop})")
            self.close_position()
            return True
        elif self.position_side == 'short' and current_price >= self.trailing_stop:
            print(f"Trailing stop hit for short position! ({current_price} >= {self.trailing_stop})")
            self.close_position()
            return True
        return False
    
    def run(self):
        """Main trading loop"""
        print(f"Starting Trailing Stop Bot for {self.symbol} (TF: {self.timeframe}, Leverage: {self.leverage}x)")
        
        while True:
            try:
                # Fetch new data and update indicators
                if self.fetch_new_data():
                    self.update_trailing_stop()
                    
                    # Check if stop was hit
                    if not self.check_stop_loss():
                        # Check for new signals if stop wasn't hit
                        self.check_signals()
                
                # Wait until next candle
                sleep_time = self.calculate_sleep_time()
                time.sleep(sleep_time)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(60)
    
    def calculate_sleep_time(self):
        """Calculate sleep time until next candle"""
        now = datetime.utcnow()
        
        if self.timeframe.endswith('m'):
            minutes = int(self.timeframe[:-1])
            next_candle = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes)
        elif self.timeframe.endswith('h'):
            hours = int(self.timeframe[:-1])
            next_candle = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours)
        else:  # Daily candles
            next_candle = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        sleep_seconds = max(10, (next_candle - now).total_seconds())
        print(f"Next update in {sleep_seconds:.1f} seconds")
        return sleep_seconds

if __name__ == "__main__":
    # Configuration
    PARAMS = {
        'key_name': 'envelope',          # Key in secret.json
        'margin_mode': 'isolated',        # Margin mode
        'mode': 'both',                   # Trading mode (long/short/both)
        'a': 1.5,                         # ATR multiplier
        'c': 14,                          # ATR period
        'use_heikin_ashi': True,          # Use Heikin-Ashi candles
        'position_size_percentage': 15    # Risk per trade (% of balance)
    }
    
    SYMBOL = "BTC/USDT:USDT"      # Trading pair
    TIMEFRAME = "15m"             # Timeframe
    LEVERAGE = 10                 # Leverage
    
    # Start bot
    bot = LiveTrailingStopBot(PARAMS, SYMBOL, TIMEFRAME, LEVERAGE)
    bot.run()
