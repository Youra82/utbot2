import os
import sys
import json
import time
import pandas as pd
import ta
from datetime import datetime, timedelta
from utilities.bitget_futures import BitgetFutures

class Strategy:
    def __init__(self, params, symbol, timeframe, leverage):
        self.params = params
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        
        # Linux-kompatible Pfadkonstruktion
        current_dir = os.path.dirname(os.path.abspath(__file__))
        key_path = os.path.join(current_dir, '../../../secret.json')
        
        try:
            with open(key_path, "r") as f:
                api_setup = json.load(f)[self.params['key_name']]
            self.exchange = BitgetFutures(api_setup)
        except FileNotFoundError:
            print(f"FEHLER: secret.json nicht gefunden unter {key_path}")
            sys.exit(1)
        except KeyError:
            print(f"FEHLER: API-Schlüssel '{self.params['key_name']}' nicht in secret.json gefunden")
            sys.exit(1)
        
        # Live-Trading Variablen
        self.position_open = False
        self.position_side = None
        self.position_size = 0
        self.trailing_stop = 0.0
        self.atr = 0.0
        
        # RISIKO- UND STRATEGIEPARAMETER - VON IHNEN KONFIGURIERBAR
        self.max_risk_percentage = params.get('max_risk_percentage', 5)  # Default 5%
        self.params.setdefault('a', 2.0)         # ATR Multiplikator
        self.params.setdefault('c', 14)           # ATR Periode
        self.params.setdefault('use_heikin_ashi', True)  # Heikin-Ashi Standardmäßig aktiviert
        self.set_trade_mode()
        
        # Exchange Einstellungen
        self.set_exchange_settings()
        
        # Initialdaten mit Fehlerbehandlung
        try:
            self.data = self.fetch_initial_data()
            self.populate_indicators()
        except Exception as e:
            print(f"FEHLER beim Datenabruf: {str(e)}")
            print("Neuer Versuch in 60 Sekunden...")
            time.sleep(60)
            self.data = self.fetch_initial_data()
            self.populate_indicators()

    def set_trade_mode(self):
        self.params.setdefault("mode", "both")
        valid_modes = ("long", "short", "both")
        if self.params["mode"] not in valid_modes:
            raise ValueError(f"Ungültiger Modus. Erlaubt: {', '.join(valid_modes)}")

        self.ignore_shorts = self.params["mode"] == "long"
        self.ignore_longs = self.params["mode"] == "short"
    
    def set_exchange_settings(self):
        """Setzt Hebel und Margin-Modus mit AWS-optimierter Fehlerbehandlung"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.exchange.set_margin_mode(self.symbol, self.params['margin_mode'])
                self.exchange.set_leverage(
                    self.symbol, 
                    self.params['margin_mode'], 
                    self.leverage
                )
                print(f"Hebel auf {self.leverage}x gesetzt ({self.params['margin_mode']} Margin)")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponentielles Backoff
                    print(f"Fehler bei Exchange-Einstellungen (Versuch {attempt+1}/{max_retries}): {str(e)}")
                    print(f"Neuer Versuch in {wait_time} Sekunden...")
                    time.sleep(wait_time)
                else:
                    print(f"Kritischer Fehler: Konnte Exchange-Einstellungen nicht setzen: {str(e)}")
                    sys.exit(1)
    
    def fetch_initial_data(self, limit=100):
        """Lädt initiale OHLCV-Daten mit Wiederholungslogik"""
        for attempt in range(3):
            try:
                print(f"Lade historische Daten für {self.symbol} ({self.timeframe})...")
                df = self.exchange.fetch_recent_ohlcv(
                    self.symbol, 
                    self.timeframe, 
                    limit
                )
                print(f"{len(df)} Kerzen geladen")
                return df
            except Exception as e:
                if attempt < 2:
                    print(f"Fehler beim Datenabruf (Versuch {attempt+1}/3): {str(e)}")
                    time.sleep(5)
                else:
                    raise
    
    def fetch_new_data(self):
        """Holt neue Marktdaten mit robustem Timeout"""
        try:
            new_df = self.exchange.fetch_recent_ohlcv(
                self.symbol, 
                self.timeframe, 
                limit=2,
                params={"timeout": 10000}  # 10 Sekunden Timeout
            )
            if not new_df.empty:
                last_timestamp = self.data.index[-1]
                new_data = new_df[new_df.index > last_timestamp]
                
                if not new_data.empty:
                    self.data = pd.concat([self.data, new_data])
                    self.populate_indicators()
                    return True
            return False
        except Exception as e:
            print(f"Warnung: Fehler beim Abruf neuer Daten: {str(e)}")
            return False
    
    def calculate_heikin_ashi(self):
        ha_close = (self.data['open'] + self.data['high'] + 
                    self.data['low'] + self.data['close']) / 4
        
        ha_open = self.data['open'].copy()
        for i in range(1, len(ha_open)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
        
        ha_high = pd.concat([self.data['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([self.data['low'], ha_open, ha_close], axis=1).min(axis=1)
        
        return ha_open, ha_high, ha_low, ha_close
        
    def populate_indicators(self):
        # HEIKIN-ASHI OPTION - VON IHNEN KONFIGURIERBAR
        use_heikin = self.params.get('use_heikin_ashi', True)
        
        if use_heikin:
            print("Verwende Heikin-Ashi Kerzen für Signalberechnung")
            ha_open, ha_high, ha_low, ha_close = self.calculate_heikin_ashi()
            src = ha_close
        else:
            print("Verwende normale Kerzen für Signalberechnung")
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
    
    def calculate_position_size(self):
        try:
            balance_data = self.exchange.fetch_balance()
            free_balance = balance_data['USDT']['free']
            
            # MAXIMALER EINSATZ - VON IHNEN FESTGELEGT
            position_value = free_balance * self.max_risk_percentage / 100
            
            print(f"Kontostand: {free_balance:.2f} USDT | Max Einsatz: {position_value:.2f} USDT ({self.max_risk_percentage}%)")
            return position_value
            
        except Exception as e:
            print(f"Fehler bei Kontostandsabfrage: {str(e)}")
            return 0  # Kein Risiko eingehen
    
    def open_position(self, side):
        try:
            position_size = self.calculate_position_size()
            if position_size <= 0:
                print("Warnung: Position zu klein, überspringe Öffnung")
                return
                
            current_price = self.data['close'].iloc[-1]
            amount = position_size / current_price
            amount = self.exchange.amount_to_precision(self.symbol, amount)
            
            min_amount = self.exchange.fetch_min_amount_tradable(self.symbol)
            if amount < min_amount:
                print(f"Warnung: Positionsgröße ({amount}) unter Minimum ({min_amount}), überspringe Öffnung")
                return
            
            if side == 'long':
                order = self.exchange.place_market_order(self.symbol, 'buy', amount)
            else:
                order = self.exchange.place_market_order(self.symbol, 'sell', amount)
            
            print(f"{side.capitalize()}-Position eröffnet: {amount} {self.symbol}")
            self.position_open = True
            self.position_side = side
            self.position_size = amount
            
            # Protokollierung für AWS CloudWatch
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "position_opened",
                "symbol": self.symbol,
                "side": side,
                "size": float(amount),
                "price": current_price,
                "leverage": self.leverage,
                "risk_percentage": self.max_risk_percentage
            }
            print(f"[TRADE_LOG] {json.dumps(log_entry)}")
            
        except Exception as e:
            print(f"Fehler beim Öffnen der Position: {str(e)}")
    
    def close_position(self):
        try:
            if not self.position_open:
                return
                
            if self.position_side == 'long':
                self.exchange.place_market_order(self.symbol, 'sell', self.position_size, reduce=True)
            else:
                self.exchange.place_market_order(self.symbol, 'buy', self.position_size, reduce=True)
            
            print(f"Position geschlossen: {self.position_size} {self.symbol}")
            
            # Protokollierung für AWS CloudWatch
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "position_closed",
                "symbol": self.symbol,
                "side": self.position_side,
                "size": float(self.position_size)
            }
            print(f"[TRADE_LOG] {json.dumps(log_entry)}")
            
            self.position_open = False
            self.position_side = None
            self.position_size = 0
            
        except Exception as e:
            print(f"Fehler beim Schließen der Position: {str(e)}")
            # Versuche später erneut
            time.sleep(5)
            self.close_position()
    
    def check_signals(self):
        last_row = self.data.iloc[-1]
        
        if self.position_open:
            if (self.position_side == 'long' and last_row['sell_signal']) or \
               (self.position_side == 'short' and last_row['buy_signal']):
                self.close_position()
        
        if not self.position_open:
            if not self.ignore_longs and last_row['buy_signal']:
                self.open_position('long')
            elif not self.ignore_shorts and last_row['sell_signal']:
                self.open_position('short')
    
    def check_stop_loss(self):
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
    
    def calculate_sleep_time(self):
        """Berechnet automatisch die Wartezeit basierend auf dem Timeframe"""
        now = datetime.utcnow()
        
        # Extrahiere Zahl und Einheit aus dem Timeframe-String
        unit = self.timeframe[-1]
        value = int(self.timeframe[:-1])
        
        if unit == 'm':  # Minuten-Timeframes
            next_candle = now.replace(second=0, microsecond=0)
            current_minute = now.minute
            minutes_to_add = value - (current_minute % value)
            
            if minutes_to_add == 0:
                minutes_to_add = value
            
            next_candle += timedelta(minutes=minutes_to_add)
        
        elif unit == 'h':  # Stunden-Timeframes
            next_candle = now.replace(minute=0, second=0, microsecond=0)
            current_hour = now.hour
            hours_to_add = value - (current_hour % value)
            
            if hours_to_add == 0:
                hours_to_add = value
            
            next_candle += timedelta(hours=hours_to_add)
        
        elif unit == 'd':  # Tages-Timeframes
            next_candle = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        
        else:  # Unbekannte Einheit
            print(f"Unbekannter Timeframe: {self.timeframe}. Verwende 1m als Backup")
            next_candle = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        
        return max(1, (next_candle - now).total_seconds())

    def run_live(self):
        print(f"Starte Live-Trading auf AWS für {self.symbol} ({self.timeframe})")
        print(f"Konfiguration: Hebel={self.leverage}x, ATR-Multiplikator={self.params['a']}, ATR-Periode={self.params['c']}")
        print(f"Risikomanagement: Max {self.max_risk_percentage}% pro Trade")
        print(f"Chartmodus: {'Heikin-Ashi' if self.params['use_heikin_ashi'] else 'Standard-Kerzen'}")
        
        while True:
            try:
                start_time = time.time()
                
                # Daten holen und verarbeiten
                data_updated = False
                try:
                    data_updated = self.fetch_new_data()
                except Exception as e:
                    print(f"Kritischer Datenabruf-Fehler: {str(e)}")
                
                if data_updated:
                    self.update_trailing_stop()
                    
                    if not self.check_stop_loss():
                        self.check_signals()
                
                # Verarbeitungszeit berücksichtigen
                processing_time = time.time() - start_time
                sleep_time = max(1, self.calculate_sleep_time() - processing_time)
                
                print(f"Zyklus abgeschlossen. Nächste Aktualisierung in {sleep_time:.1f}s")
                time.sleep(sleep_time)
                
            except Exception as e:
                print(f"KRITISCHER FEHLER: {str(e)}")
                print("Neustart in 60 Sekunden...")
                time.sleep(60)

if __name__ == "__main__":
    # KONFIGURATION - HIER KÖNNEN SIE ALLE PARAMETER ANPASSEN
    PARAMS = {
        'key_name': 'envelope',          # Schlüssel in secret.json
        'margin_mode': 'isolated',       # Margin-Modus (isolated/cross)
        'mode': 'both',                  # Handelsrichtung (long/short/both)
        'a': 2.0,                        # ATR Multiplikator (Sensitivität)
        'c': 14,                         # ATR Periode
        'use_heikin_ashi': True,         # HEIKIN-ASHI AKTIVIEREN/DEAKTIVIEREN (True/False)
        'max_risk_percentage': 5         # Maximaler Einsatz in % des Kontos
    }
    
    SYMBOL = "BTC/USDT:USDT"      # Handelscoin
    TIMEFRAME = "15m"             # Zeitrahmen
    LEVERAGE = 10                 # Hebel
    
    # Server-Startprotokollierung
    print("=" * 70)
    print(f"Trading Bot gestartet um {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Handelspaar: {SYMBOL} | Zeitrahmen: {TIMEFRAME} | Hebel: {LEVERAGE}x")
    print(f"Maximaler Einsatz: {PARAMS['max_risk_percentage']}% | Heikin-Ashi: {'Aktiviert' if PARAMS['use_heikin_ashi'] else 'Deaktiviert'}")
    print("=" * 70)
    
    # Bot starten mit Ausnahmebehandlung
    bot = None
    try:
        bot = Strategy(PARAMS, SYMBOL, TIMEFRAME, LEVERAGE)
        bot.run_live()
    except KeyboardInterrupt:
        print("\nBot manuell gestoppt")
        sys.exit(0)
    except Exception as e:
        print(f"UNBEHANDELTER FEHLER: {str(e)}")
        if bot and bot.position_open:
            print("Versuche offene Position zu schließen...")
            bot.close_position()
        print("Neustart in 60 Sekunden...")
        time.sleep(60)
        # Automatischer Neustart
        os.execv(sys.executable, ['python'] + sys.argv)
