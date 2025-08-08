import pandas as pd
import ta
import time
from datetime import datetime
import json
import os
import sys
from ...utilities.bitget_futures import BitgetFutures

# 1. Konfigurationsparameter - HIER KÖNNEN DIE EINSTELLUNGEN VORGENOMMEN WERDEN
CONFIG = {
    'symbols': ['BTCUSDT'],      # Handelsinstrumente
    'timeframe': '15m',          # Zeitrahmen: 1m, 5m, 15m, 30m, 1h, 4h, 1d
    'leverage': 10,              # Hebel (1-100)
    'use_heikin_ashi': True,     # Heikin-Ashi-Kerzen verwenden
    'position_size': {           # Einsatz pro Trade
        'type': 'percentage',    # 'percentage' oder 'fixed'
        'value': 5               # 5% des Kontos oder fester Betrag
    },
    'strategy_params': {         # Indikatorparameter
        'a': 1.0,                # Key Value (Sensitivität)
        'c': 10                  # ATR Periode
    },
    'mode': 'both',              # Handelsmodus: 'long', 'short', 'both'
    'api_setup_name': 'envelope' # API-Schlüssel in secret.json
}

class Strategy:
    def __init__(self, params, ohlcv) -> None:
        self.params = params
        self.data = ohlcv.copy()
        self.populate_indicators()
        self.set_trade_mode()
        
    def set_trade_mode(self):
        self.ignore_shorts = self.params["mode"] == "long"
        self.ignore_longs = self.params["mode"] == "short"
        
    def calculate_heikin_ashi(self):
        ha_close = (self.data['open'] + self.data['high'] + self.data['low'] + self.data['close']) / 4
        ha_open = self.data['open'].copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        ha_high = pd.concat([self.data['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([self.data['low'], ha_open, ha_close], axis=1).min(axis=1)
        return ha_open, ha_high, ha_low, ha_close
        
    def populate_indicators(self):
        # Heikin-Ashi aktivieren/deaktivieren
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
        
        # Signale generieren
        self.data['buy_signal'] = (src > trailing_stop) & (src.shift(1) <= trailing_stop.shift(1))
        self.data['sell_signal'] = (src < trailing_stop) & (src.shift(1) >= trailing_stop.shift(1))

def load_api_credentials():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    secret_path = os.path.join(base_dir, 'secret.json')
    
    try:
        with open(secret_path, 'r') as f:
            secrets = json.load(f)
            return secrets[CONFIG['api_setup_name']]
    except Exception as e:
        print(f"Fehler beim Laden der API-Keys: {e}")
        sys.exit(1)

def calculate_position_size(balance):
    if CONFIG['position_size']['type'] == 'percentage':
        return balance * CONFIG['position_size']['value'] / 100
    else:
        return CONFIG['position_size']['value']

def run_trading_bot():
    # API initialisieren
    api_credentials = load_api_credentials()
    exchange = BitgetFutures({
        'apiKey': api_credentials['apiKey'],
        'secret': api_credentials['secret'],
        'password': api_credentials['password']
    })
    
    # Hebel für alle Symbole setzen
    for symbol in CONFIG['symbols']:
        exchange.set_margin_mode(symbol, 'isolated')
        exchange.set_leverage(symbol, 'isolated', CONFIG['leverage'])
        print(f"Für {symbol}: Hebel {CONFIG['leverage']}x gesetzt")
    
    print("\nTrading Bot gestartet. Drücke Strg+C zum Beenden.\n")
    
    while True:
        try:
            # Kontostand abfragen
            balance_data = exchange.fetch_balance()
            usdt_balance = float(balance_data['USDT']['total'])
            print(f"Aktueller Kontostand: {usdt_balance:.2f} USDT")
            
            for symbol in CONFIG['symbols']:
                # OHLCV-Daten abrufen (direkt als DataFrame)
                df = exchange.fetch_recent_ohlcv(symbol, CONFIG['timeframe'], limit=1000)
                
                # Strategie anwenden
                strategy_params = {
                    'a': CONFIG['strategy_params']['a'],
                    'c': CONFIG['strategy_params']['c'],
                    'use_heikin_ashi': CONFIG['use_heikin_ashi'],
                    'mode': CONFIG['mode']
                }
                strategy = Strategy(strategy_params, df)
                
                # Letzten Datenpunkt analysieren
                last_row = strategy.data.iloc[-1]
                positions = exchange.fetch_open_positions(symbol)
                has_position = len(positions) > 0
                
                print(f"\n{symbol} - {datetime.now().strftime('%H:%M:%S')}")
                print(f"Preis: {last_row['close']:.2f}")
                print(f"Signal: {'Kauf' if last_row['buy_signal'] else 'Verkauf' if last_row['sell_signal'] else 'Kein Signal'}")
                print(f"Position: {'Ja' if has_position else 'Nein'}")
                
                # Handel ausführen
                if not has_position:
                    trade_size = calculate_position_size(usdt_balance)
                    
                    # Amount präzisieren
                    trade_size = exchange.amount_to_precision(symbol, trade_size)
                    
                    if last_row['buy_signal'] and not strategy.ignore_longs:
                        exchange.place_market_order(
                            symbol, 
                            'buy', 
                            trade_size,
                            reduce=False
                        )
                        print(f"↗️ LONG Position eröffnet: {trade_size:.2f} USDT")
                        
                    elif last_row['sell_signal'] and not strategy.ignore_shorts:
                        exchange.place_market_order(
                            symbol, 
                            'sell', 
                            trade_size,
                            reduce=False
                        )
                        print(f"↘️ SHORT Position eröffnet: {trade_size:.2f} USDT")
                
                # Warten bis zum nächsten Durchlauf
                time_frame_minutes = int(CONFIG['timeframe'].rstrip('m'))
                sleep_time = time_frame_minutes * 60
                print(f"\nNächste Prüfung in {time_frame_minutes} Minuten...")
                time.sleep(sleep_time)
                
        except Exception as e:
            print(f"Fehler: {e}")
            time.sleep(60)
        except KeyboardInterrupt:
            print("\nBot gestoppt")
            sys.exit(0)

if __name__ == "__main__":
    run_trading_bot()
