# utils/exchange_handler.py
import ccxt
import logging
import pandas as pd
import time

# GEÄNDERT: Logger-Name angepasst
logger = logging.getLogger('utbot2')

class ExchangeHandler:
    def __init__(self, api_setup=None):
        if api_setup:
            self.session = ccxt.bitget({
                'apiKey': api_setup['apiKey'],
                'secret': api_setup['secret'],
                'password': api_setup['password'],
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
            logger.error(f"Fehler beim Setzen des Hebels für {symbol}: {e}")
            raise

    def fetch_usdt_balance(self):
        try:
            balance = self.session.fetch_balance()
            for item in balance['info']['data']:
                if item['marginCoin'] == 'USDT':
                    return float(item['availableBalance'])
            return 0.0
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des USDT-Guthabens: {e}")
            raise

    def fetch_ohlcv(self, symbol, timeframe, limit):
        try:
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Fehler beim Laden der Kerzendaten für {symbol}: {e}")
            raise

    def fetch_open_positions(self, symbol: str):
        try:
            all_positions = self.session.fetch_positions([symbol])
            return [p for p in all_positions if p.get('contracts') is not None and float(p['contracts']) > 0]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der offenen Positionen für {symbol}: {e}")
            raise

    def fetch_trade_history(self, symbol: str, since_timestamp: int):
        try:
            time.sleep(2)
            return self.session.fetch_my_trades(symbol, since=since_timestamp, limit=50)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Handelshistorie für {symbol}: {e}")
            raise

    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        try:
            params = {
                'stopLossPrice': self.session.price_to_precision(symbol, sl_price),
                'takeProfitPrice': self.session.price_to_precision(symbol, tp_price),
            }
            return self.session.create_order(symbol, 'market', side, amount, params=params)
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Market-Order für {symbol}: {e}")
            raise
