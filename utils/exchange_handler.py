# utils/exchange_handler.py
import ccxt
import logging
import pandas as pd
import time

logger = logging.getLogger('utbot2')

class ExchangeHandler:
    def __init__(self, api_setup=None):
        if api_setup:
            self.session = ccxt.bitget({
                'apiKey': api_setup['apiKey'], 'secret': api_setup['secret'], 'password': api_setup['password'],
                'options': { 'defaultType': 'swap' },
            })
        else:
            self.session = ccxt.bitget({'options': { 'defaultType': 'swap' }})
        self.session.load_markets()

    def set_leverage(self, symbol: str, leverage: int):
        try:
            # Wichtig: Wie in deinem JaegerBot-Beispiel, den Hebel für beide Seiten setzen
            self.session.set_leverage(leverage, symbol, {'marginMode': 'isolated', 'holdSide': 'long'})
            self.session.set_leverage(leverage, symbol, {'marginMode': 'isolated', 'holdSide': 'short'})
            logger.info(f"Hebel für {symbol} erfolgreich auf {leverage}x gesetzt.")
        except Exception as e:
            if 'repeat submit' in str(e) or 'Leverage not changed' in str(e):
                logger.info(f"Hebel für {symbol} ist bereits auf {leverage}x gesetzt.")
            else:
                logger.error(f"Fehler beim Setzen des Hebels: {e}"); raise

    def fetch_usdt_balance(self):
        try:
            balance = self.session.fetch_balance()
            if 'USDT' in balance and 'free' in balance['USDT']:
                return float(balance['USDT']['free'])
            return 0.0
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Guthabens: {e}"); raise

    def fetch_ohlcv(self, symbol, timeframe, limit):
        try:
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Fehler beim Laden der Kerzendaten: {e}"); raise

    def fetch_open_positions(self, symbol: str):
        try:
            all_positions = self.session.fetch_positions([symbol])
            return [p for p in all_positions if p.get('contracts') is not None and float(p['contracts']) > 0]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen offener Positionen: {e}"); raise

    def fetch_trade_history(self, symbol: str, since_timestamp: int):
        try:
            time.sleep(2)
            return self.session.fetch_my_trades(symbol, since=since_timestamp, limit=50)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Trade-Historie: {e}"); raise
            
    # --- Private Hilfsfunktion, inspiriert von deinem JaegerBot ---
    def _place_trigger_order(self, symbol: str, side: str, amount: float, trigger_price: float, params: dict = None):
        """Platziert eine SL- oder TP-Order als Trigger-Market-Order."""
        order_params = {'stopPrice': trigger_price, **(params or {})}
        return self.session.create_order(symbol, 'market', side, amount, None, order_params)

    # --- FINALE ORDER-LOGIK, 1:1 NACH DEM JAEGERBOT-PRINZIP ---
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        try:
            # Schritt 1: Reine Market-Order zur Eröffnung
            logger.info(f"Schritt 1: Eröffne reine Market-Order für {symbol}...")
            order = self.session.create_order(symbol, 'market', side, amount)
            
            logger.info("Warte 5 Sekunden, damit die Position an der Börse vollständig erfasst wird...")
            time.sleep(5)

            close_side = 'sell' if side == 'buy' else 'buy'
            
            # Schritt 2: Separate Trigger-Order für den Take-Profit
            logger.info(f"Schritt 2: Setze Take-Profit als separate Trigger-Order bei {tp_price}...")
            self._place_trigger_order(symbol, close_side, amount, tp_price, {'reduceOnly': True})

            # Schritt 3: Separate Trigger-Order für den Stop-Loss
            logger.info(f"Schritt 3: Setze Stop-Loss als separate Trigger-Order bei {sl_price}...")
            self._place_trigger_order(symbol, close_side, amount, sl_price, {'reduceOnly': True})

            return order
        except Exception as e:
            logger.error(f"Fehler im finalen Order-Prozess: {e}"); raise
