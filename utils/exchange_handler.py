# utbot2/utils/exchange_handler.py
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime

logger = logging.getLogger('utbot2')


class ExchangeHandler:
    def __init__(self, api_setup=None):
        """Initialisiert die Bitget-Session."""
        if api_setup:
            self.session = ccxt.bitget({
                'apiKey': api_setup['apiKey'],
                'secret': api_setup['secret'],
                'password': api_setup['password'],
                'options': {'defaultType': 'swap'},
            })
        else:
            self.session = ccxt.bitget({'options': {'defaultType': 'swap'}})
        self.markets = self.session.load_markets()
        logger.info("ExchangeHandler initialisiert und Märkte geladen.")

    # -------------------
    # --- Basis-Funktionen
    # -------------------

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        """Lädt OHLCV-Daten."""
        try:
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                logger.warning(f"[{symbol}] Keine OHLCV-Daten erhalten.")
                return pd.DataFrame()

            df = pd.DataFrame(
                ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df = df.sort_index()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Laden der Kerzendaten: {e}", exc_info=True)
            raise

    def fetch_ticker(self, symbol):
        """Holt aktuellen Ticker."""
        try:
            return self.session.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen des Tickers: {e}", exc_info=True)
            raise

    def fetch_balance_usdt(self):
        """Holt das verfügbare USDT-Guthaben."""
        try:
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            balance = self.session.fetch_balance(params=params)
            usdt_balance = 0.0

            if 'USDT' in balance and 'free' in balance['USDT'] and balance['USDT']['free'] is not None:
                usdt_balance = float(balance['USDT']['free'])
            elif 'info' in balance and 'data' in balance['info'] and isinstance(balance['info']['data'], list):
                for asset_info in balance['info']['data']:
                    if asset_info.get('marginCoin') == 'USDT':
                        if 'available' in asset_info and asset_info['available'] is not None:
                            usdt_balance = float(asset_info['available'])
                            break
                        elif 'equity' in asset_info and asset_info['equity'] is not None:
                            logger.warning("Verwende 'equity' als Fallback für Guthaben.")
                            usdt_balance = float(asset_info['equity'])
            elif 'free' in balance and 'USDT' in balance['free']:
                usdt_balance = float(balance['free']['USDT'])
            elif 'total' in balance and 'USDT' in balance['total']:
                usdt_balance = float(balance['total']['USDT'])

            if usdt_balance == 0.0:
                logger.warning("Kein USDT-Guthaben gefunden.")
            return usdt_balance
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des USDT-Guthabens: {e}", exc_info=True)
            return 0.0

    def fetch_open_positions(self, symbol: str):
        """Holt alle offenen Positionen für ein Symbol."""
        try:
            params = {'productType': 'USDT-FUTURES'}
            positions = self.session.fetch_positions([symbol], params=params)
            open_positions = []
            for p in positions:
                try:
                    contracts = float(p.get('contracts', 0))
                    if abs(contracts) > 1e-9:
                        open_positions.append(p)
                except Exception:
                    continue
            return open_positions
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Positionen: {e}", exc_info=True)
            raise

    def fetch_open_trigger_orders(self, symbol: str):
        """Holt offene Trigger-Orders (SL/TP)."""
        try:
            params = {'stop': True, 'productType': 'USDT-FUTURES'}
            return self.session.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Trigger-Orders: {e}", exc_info=True)
            return []

    def cleanup_all_open_orders(self, symbol: str):
        """Storniert alle offenen Orders (Normal + Trigger)."""
        cancelled_count = 0
        for stop_flag in [False, True]:
            try:
                params = {'productType': 'USDT-FUTURES', 'stop': stop_flag}
                self.session.cancel_all_orders(symbol, params=params)
                cancelled_count += 1
                type_str = "Trigger" if stop_flag else "Normal"
                logger.info(f"[{symbol}] Housekeeper: 'cancel_all_orders' ({type_str}) gesendet.")
                time.sleep(0.5)
            except ccxt.ExchangeError as e:
                if any(x in str(e).lower() for x in ['order not found', 'no order to cancel', '22001']):
                    type_str = "Trigger" if stop_flag else "Normal"
                    logger.info(f"[{symbol}] Housekeeper: Keine {type_str}-Orders zum Stornieren gefunden.")
                else:
                    logger.error(f"[{symbol}] Housekeeper: Fehler beim Stornieren: {e}")
            except Exception as e:
                logger.error(f"[{symbol}] Housekeeper: Unerwarteter Fehler: {e}")
        return cancelled_count

    # -------------------
    # --- Hebel & Margin
    # -------------------

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        """Setzt Hebel & Margin-Modus."""
        leverage = max(1, int(round(leverage)))
        try:
            params_margin = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            try:
                self.session.set_margin_mode(margin_mode.lower(), symbol, params=params_margin)
            except ccxt.ExchangeError:
                pass
            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            if margin_mode.lower() == 'isolated':
                self.session.set_leverage(leverage, symbol, params={**params, 'holdSide': 'long', 'posSide': 'net'})
                self.session.set_leverage(leverage, symbol, params={**params, 'holdSide': 'short', 'posSide': 'net'})
            else:
                self.session.set_leverage(leverage, symbol, params={**params, 'posSide': 'net'})
            logger.info(f"[{symbol}] Hebel auf {leverage}x ({margin_mode}) gesetzt.")
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Setzen von Hebel/Margin: {e}", exc_info=True)
            raise

    # -------------------
    # --- Order Platzierung
    # -------------------

    def create_market_order(self, symbol: str, side: str, amount: float, params: dict = {}):
        """Erstellt eine Market-Order robust."""
        try:
            order_params = {**params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES'

            # Remove marginMode if reduceOnly
            is_reduce_only = str(order_params.get('reduceOnly', 'false')).lower() == 'true' or order_params.get('reduceOnly') == 'YES'
            if is_reduce_only and 'marginMode' in order_params:
                del order_params['marginMode']

            rounded_amount = float(self.session.amount_to_precision(symbol, amount))
            if rounded_amount <= 0:
                logger.error(f"[{symbol}] Market-Order-Betrag <= 0 ({rounded_amount})")
                return None

            logger.info(f"[{symbol}] Sende Market-Order: {side} {rounded_amount} | Params={order_params}")
            order = self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            logger.info(f"[{symbol}] Market-Order erfolgreich. ID: {order.get('id')}")
            return order
        except ccxt.ExchangeError as e:
            if '22002' in str(e):
                logger.warning(f"[{symbol}] Keine Position zum Schließen (reduceOnly).")
                return None
            logger.error(f"[{symbol}] Exchange-Fehler Market-Order: {e}")
            raise
        except Exception as e:
            logger.error(f"[{symbol}] Unerwarteter Fehler Market-Order: {e}", exc_info=True)
            raise

    def place_trigger_market_order(self, symbol, side, amount, trigger_price, params={}):
        """Platzierung von Trigger-Market-Orders (SL/TP)."""
        try:
            rounded_price = float(self.session.price_to_precision(symbol, trigger_price))
            rounded_amount = float(self.session.amount_to_precision(symbol, amount))
            order_params = {**params, 'triggerPrice': rounded_price, 'reduce
