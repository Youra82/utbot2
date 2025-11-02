# utbot2/utils/exchange_handler.py (Version 4.3 - DREI-SCHRITT Logik)
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime, timezone

logger = logging.getLogger('utbot2')

class ExchangeHandler:
    def __init__(self):
        """Initialisiert die Bitget-Session (extern in main.py gesetzt)."""
        self.session = None 
        self.markets = None 

    # --- HILFSFUNKTIONEN (Unverändert) ---
    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        # ... (Logik wie im vorherigen Code)
        try:
             ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
             if not ohlcv: return pd.DataFrame()
             df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
             df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
             df.set_index('timestamp', inplace=True)
             df.sort_index(inplace=True)
             for col in ['open', 'high', 'low', 'close', 'volume']:
                 df[col] = pd.to_numeric(df[col], errors='coerce')
             return df
        except Exception as e:
             raise

    def fetch_ticker(self, symbol):
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            return self.session.fetch_ticker(symbol)
        except Exception as e:
            raise
    
    def fetch_balance_usdt(self):
        # ... (Logik wie im vorherigen Code)
        try:
            if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'reload': True}
            balance = self.session.fetch_balance(params=params)
            usdt_balance = 0.0
            if 'USDT' in balance and 'free' in balance['USDT'] and balance['USDT']['free'] is not None:
                 usdt_balance = float(balance['USDT']['free'])
            return usdt_balance
        except Exception as e:
            return 0.0

    def fetch_open_positions(self, symbol: str):
        # ... (Logik wie im vorherigen Code)
        try:
            if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
            params = {'productType': 'USDT-FUTURES', 'reload': True}
            positions = self.session.fetch_positions([symbol], params=params)
            open_positions = [p for p in positions if abs(float(p.get('contracts', 0))) > 1e-9]
            return open_positions
        except Exception as e:
            raise
            
    # --- RUMPFFUNKTIONEN ZUM PASSEN DES LIVE-CODES ---
    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            self.session.set_margin_mode(margin_mode, symbol, params={'productType': 'USDT-FUTURES'})
            self.session.set_leverage(leverage, symbol, params={'productType': 'USDT-FUTURES'})
        except Exception:
            pass 
        return True 

    def create_market_order(self, symbol, side, amount, params={}):
        """ Erstellt eine einfache Market Order (wird vom Workaround benötigt). """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
             order_params = {**params}
             if 'productType' not in order_params: order_params['productType'] = 'USDT-FUTURES'
             return self.session.create_order(symbol, 'market', side, amount, params=order_params)
        except Exception as e:
             raise e

    def fetch_open_trigger_orders(self, symbol: str):
        """ Holt offene Trigger Orders (vom Test benötigt). """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            params = {'stop': True, 'productType': 'USDT-FUTURES', 'reload': True}
            return self.session.fetch_open_orders(symbol, params=params)
        except Exception as e:
            return []

    def cleanup_all_open_orders(self, symbol: str):
        """ Storniert alle offenen Orders (vom Test und main.py benötigt). """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            self.session.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES', 'stop': False})
            self.session.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES', 'stop': True})
            return 1 
        except Exception:
            return 0
    # --- ENDE RUMPFFUNKTIONEN ---


    # --- ZENTRALE FUNKTION: DREI-SCHRITT TRADE (TitanBot-Logik) ---
    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, params: dict = {}):
        """ Platziert eine SL- oder TP-Order als Trigger-Market-Order (TitanBot/JaegerBot-Logik). """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            rounded_price = float(self.session.price_to_precision(symbol, trigger_price))
            rounded_amount = float(self.session.amount_to_precision(symbol, amount))

            order_params = {
                'triggerPrice': rounded_price,
                'reduceOnly': True,
                'productType': 'USDT-FUTURES',
                'planType': 'Plan',  # Generische Plan Order für Bitget
                'stopLossTriggerPriceType': 'market_price', 
                'takeProfitTriggerPriceType': 'market_price',
                **params
            }

            # Wichtig für den One-Way-Mode
            order_params['posSide'] = 'net'
            order_params['tradeSide'] = 'close'

            return self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)

        except Exception as e:
            logger.error(f"[{symbol}] FEHLER beim Platzieren des Triggers: {e}", exc_info=True)
            raise

    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str,
                                      tsl_config: dict = None):
        """
        Führt den robusten 3-Schritt-Prozess zur Trade-Eröffnung aus: 
        1. Market Order, 2. SL, 3. TP (TitanBot-Stil).
        """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        logger.info(f"[{symbol}] Starte 3-Schritt Order-Platzierung: {side}, Menge={amount}, SL={sl_price}, TP={tp_price}")

        # 1. Market-Order (Einstieg)
        try:
            market_params = {
                'posSide': 'net',
                'tradeSide': 'open'
            }
            # Der Aufruf an create_market_order, die den Trade öffnet.
            market_order = self.create_market_order(symbol, side, amount, params=market_params) 

            # Hier ist der kritische Unterschied: wir MÜSSEN die tatsächliche Position bestätigen
            time.sleep(3) # Warte auf Füllung

            final_position = self.fetch_open_positions(symbol)
            if not final_position:
                raise Exception("Position konnte nach Market-Order nicht bestätigt werden.")

            final_amount = float(final_position[0]['contracts'])
            actual_entry_price = float(final_position[0]['entryPrice'])
            
            market_order['average'] = actual_entry_price
            market_order['filled'] = final_amount
            
            logger.info(f"[{symbol}] Schritt 1/3: ✅ Market-Order platziert und Position bestätigt.")

        except Exception as e:
            logger.error(f"[{symbol}] ❌ SCHRITT 1 FEHLGESCHLAGEN: {e}. Breche Trade ab.")
            # Aufräumen, falls nur die Market Order durchging
            self.cleanup_all_open_orders(symbol)
            raise

        close_side = 'sell' if side == 'buy' else 'buy'
        trigger_params = {'reduceOnly': True, 'productType': 'USDT-FUTURES'}
        
        # 2. Stop-Loss (Immer fixer SL, da TSL zu unzuverlässig ist)
        try:
            logger.info(f"[{symbol}] Schritt 2/3: Platziere Stop-Loss bei {sl_price}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, sl_price, params=trigger_params)
            logger.info(f"[{symbol}] Schritt 2/3: ✅ Fixen Stop-Loss platziert.")

        except Exception as e_sl:
            logger.error(f"[{symbol}] ❌ KRITISCH: SL-Order fehlgeschlagen: {e_sl}. Position ist UNGESCHÜTZT!")
            self.cleanup_all_open_orders(symbol)
            raise

        # 3. Take-Profit
        try:
            logger.info(f"[{symbol}] Schritt 3/3: Platziere Take-Profit bei {tp_price}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, tp_price, params=trigger_params)
            logger.info(f"[{symbol}] Schritt 3/3: ✅ Take-Profit platziert.")
        except Exception as e_tp:
            logger.error(f"[{symbol}] ❌ WARNUNG: TP-Order fehlgeschlagen: {e_tp}.") # Nur Warnung, kein Abbruch

        return market_order
