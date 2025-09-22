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

    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        try:
            # Schritt 1: Erstelle die reine Market-Order, um die Position zu eröffnen
            logger.info(f"Schritt 1: Eröffne Market-Order für {symbol}...")
            order = self.session.create_order(symbol, 'market', side, amount)
            
            logger.info("Warte 5 Sekunden, bis die Position vollständig erstellt ist...")
            time.sleep(5)

            # Schritt 2: Setze SL und TP für die existierende Position
            logger.info(f"Schritt 2: Setze SL ({sl_price}) und TP ({tp_price}) für die neue Position...")
            sl_tp_params = {
                'stopLossPrice': self.session.price_to_precision(symbol, sl_price),
                'takeProfitPrice': self.session.price_to_precision(symbol, tp_price),
            }
            # Dieser API-Call modifiziert eine bestehende Position
            self.session.private_post_mix_v2_position_set_tpsl_position(
                {'symbol': self.session.market(symbol)['id'], **sl_tp_params}
            )
            return order
        except Exception as e:
            logger.error(f"Fehler im Order-Prozess: {e}"); raise
