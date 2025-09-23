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
            self.session.set_leverage(leverage, symbol)
            logger.info(f"Hebel für {symbol} erfolgreich auf {leverage}x gesetzt.")
        except Exception as e:
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
            
    # --- FINALE, ROBUSTE ORDER-LOGIK (inspiriert von JaegerBot) ---
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        try:
            # Schritt 1: Reine Market-Order zur Eröffnung der Position
            logger.info(f"Schritt 1: Eröffne Market-Order für {symbol} ({side}, {amount})...")
            order = self.session.create_order(symbol, 'market', side, amount)
            
            logger.info("Warte 5 Sekunden, damit die Position vollständig erstellt ist...")
            time.sleep(5)

            # Schritt 2: Separate Trigger-Order für den Take-Profit
            tp_side = 'sell' if side == 'buy' else 'buy'
            logger.info(f"Schritt 2: Setze Take-Profit bei {tp_price}...")
            tp_params = {'stopPrice': tp_price, 'reduceOnly': True}
            self.session.create_order(symbol, 'market', tp_side, amount, params=tp_params)

            # Schritt 3: Separate Trigger-Order für den Stop-Loss
            sl_side = 'sell' if side == 'buy' else 'buy'
            logger.info(f"Schritt 3: Setze Stop-Loss bei {sl_price}...")
            sl_params = {'stopPrice': sl_price, 'reduceOnly': True}
            self.session.create_order(symbol, 'market', sl_side, amount, params=sl_params)

            return order
        except Exception as e:
            logger.error(f"Fehler im finalen Order-Prozess: {e}"); raise
