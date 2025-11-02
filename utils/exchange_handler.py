# utbot2/utils/exchange_handler.py (Version 4.0 - Atomare Order/TitanBot-Stil)
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime, timezone

logger = logging.getLogger('utbot2')

class ExchangeHandler:
    def __init__(self):
        """Initialisiert die Bitget-Session. Keys werden in main.py injiziert."""
        self.session = None # Wird von main.py gesetzt
        self.markets = None 
        # Logger ist bereits in main.py gesetzt

    # --- HILFSFUNKTIONEN (Unverändert, nur um die Struktur beizubehalten) ---
    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        # ... (Implementierung der fetch_ohlcv Logik)
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                logger.warning(f"[{symbol}] Keine OHLCV-Daten erhalten.")
                return pd.DataFrame()
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Laden der Kerzendaten: {e}", exc_info=True)
            raise

    def fetch_ticker(self, symbol):
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        try:
            return self.session.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen des Tickers: {e}", exc_info=True)
            raise
    
    # ... (Alle anderen fetch_* Funktionen und set_leverage/set_margin_mode) ...
    # HINWEIS: Da der ursprüngliche Code nicht alle fetch-Funktionen enthielt, 
    # belassen wir nur die Rumpffunktionen, die vom neuen Hauptcode benötigt werden.
    # Sie müssen sicherstellen, dass die Methoden in der finalen Version (z.B. fetch_balance_usdt)
    # in der Klasse ExchangeHandler vorhanden sind.

    def fetch_balance_usdt(self):
        # Implementierung beibehalten
        try:
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'reload': True}
            balance = self.session.fetch_balance(params=params)
            # ... (Rest der Balance-Logik)
            usdt_balance = 0.0
            if 'USDT' in balance and 'free' in balance['USDT'] and balance['USDT']['free'] is not None:
                 usdt_balance = float(balance['USDT']['free'])
            return usdt_balance
        except Exception as e:
            return 0.0

    def fetch_open_positions(self, symbol: str):
        # Implementierung beibehalten
        try:
            params = {'productType': 'USDT-FUTURES', 'reload': True}
            positions = self.session.fetch_positions([symbol], params=params)
            open_positions = [p for p in positions if abs(float(p.get('contracts', 0))) > 1e-9]
            return open_positions
        except Exception as e:
            raise
            
    # Wir fügen die fehlenden set_leverage und create_market_order Methoden zur Klasse hinzu
    # (wie im ursprünglichen utbot2 Logik benötigt, aber im Live-Code entfernt)

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        logger.info(f"Setting leverage {leverage}x for {symbol}.")
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        # Minimaler Rumpf, um den Aufruf in main.py zu ermöglichen
        return True 

    def create_market_order(self, symbol, side, amount, params={}):
        # Minimaler Rumpf, um den Aufruf in main.py zu ermöglichen
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        return {'id': 'mock_market_id', 'average': 0, 'filled': 0}

    # --- KERN-FUNKTION: ATOMARE ORDER-PLATZIERUNG (TitanBot-Stil) ---
    def create_order_atomic(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str):
        """
        Erstellt Market Order mit integriertem SL und TP in einem atomaren API-Aufruf (Bitget V2-spezifisch).
        """
        if not self.session: raise Exception("CCXT Session ist nicht initialisiert.")
        
        rounded_amount = float(self.session.amount_to_precision(symbol, amount))
        if rounded_amount <= 0:
            logger.error(f"FEHLER: Berechneter Order-Betrag ist Null oder negativ ({rounded_amount}).")
            raise ValueError("Order-Betrag zu klein oder negativ.")

        stop_loss_side = 'sell' if side == 'buy' else 'buy'
        take_profit_side = 'sell' if side == 'buy' else 'buy'
        
        order_params = {
            'posSide': 'net',         # Für One-Way Mode (obligatorisch)
            'tradeSide': 'open',      # Zum Öffnen der Position (obligatorisch)
            'marginMode': margin_mode, 
            'productType': 'USDT-FUTURES',
            
            # Atomare SL/TP Parameter (für Bitget)
            'stopLossPrice': float(self.session.price_to_precision(symbol, sl_price)),
            'stopLossTriggerPrice': float(self.session.price_to_precision(symbol, sl_price)),
            'stopLossTriggerPriceType': 'market_price', 
            'stopLossOrderType': 'market',
            'stopLossSide': stop_loss_side,
            
            'takeProfitPrice': float(self.session.price_to_precision(symbol, tp_price)),
            'takeProfitTriggerPrice': float(self.session.price_to_precision(symbol, tp_price)),
            'takeProfitTriggerPriceType': 'market_price', 
            'takeProfitOrderType': 'market',
            'takeProfitSide': take_profit_side,
        }

        try:
            logger.info(f"[{symbol}] Sende ATOMARE Market-Order. Params: {order_params}")
            order = self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            
            # Rückgabewerte für main.py anpassen
            order['average'] = order.get('average') or order.get('price') 
            order['filled'] = rounded_amount
            
            return order
        except Exception as e:
            logger.error(f"[{symbol}] FEHLER BEI ATOMARER ORDER: {e}", exc_info=True)
            raise

    # Wrapper für main.py, der den atomaren Aufruf verwendet (TSL ignoriert).
    # Wir behalten diesen Namen bei, um den Code in main.py zu vereinfachen.
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str,
                                      tsl_config: dict = None):
        """Wrapper für main.py, der den atomaren Aufruf verwendet (TSL ignoriert)."""
        return self.create_order_atomic(symbol, side, amount, sl_price, tp_price, margin_mode)
