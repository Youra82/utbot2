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
            if 'USDT' in balance and 'free' in balance['USDT']:
                return float(balance['USDT']['free'])
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

    # --- DIESE FUNKTION IST ENTSCHEIDEND ---
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        """
        Erstellt eine Market-Order und platziert dann SL und TP in separaten Folge-Orders,
        wie von der Bitget API gefordert.
        """
        try:
            # Schritt 1: Erstelle die initiale Market-Order
            logger.info(f"Schritt 1: Erstelle Market-Order für {symbol} ({side}, {amount})...")
            # Wir können versuchen, den Take-Profit hier zu setzen, da er oft als Teil der "Plan Order" erlaubt ist.
            plan_order_params = {'takeProfitPrice': self.session.price_to_precision(symbol, tp_price)}
            order = self.session.create_order(symbol, 'market', side, amount, params=plan_order_params)
            
            # Gib der Börse einen Moment Zeit, die Order zu verarbeiten und die Position zu erstellen
            logger.info("Warte 5 Sekunden, damit die Position erstellt werden kann...")
            time.sleep(5)
            
            # Schritt 2: Erstelle eine separate Stop-Loss-Order für die nun offene Position
            logger.info(f"Schritt 2: Setze separaten Stop-Loss bei {sl_price}...")
            sl_side = 'sell' if side == 'buy' else 'buy'
            sl_params = {
                'stopLossPrice': self.session.price_to_precision(symbol, sl_price),
                'reduceOnly': True # Stellt sicher, dass die Order nur schließt, niemals eine neue Position eröffnet
            }
            self.session.create_order(symbol, 'market', sl_side, amount, params=sl_params)
            
            return order
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Market-Order mit SL/TP: {e}")
            raise
