# /home/matola/titanbot/src/titanbot/utils/exchange.py
# KORRIGIERTE VERSION - ATOMARER ORDER/TITANBOT STIL
import ccxt
import pandas as pd
from datetime import datetime, timezone, timedelta
import time
import logging

logger = logging.getLogger(__name__)

class Exchange:
    def __init__(self, account_config):
        self.account = account_config
        self.exchange = getattr(ccxt, 'bitget')({
            'apiKey': self.account.get('apiKey'),
            'secret': self.account.get('secret'),
            'password': self.account.get('password'),
            'options': {
                'defaultType': 'swap',
            },
            'enableRateLimit': True,
        })
        try:
            self.markets = self.exchange.load_markets()
            logger.info("Bitget Märkte erfolgreich geladen.")
        except ccxt.AuthenticationError as e:
            logger.critical(f"FATAL: Bitget Authentifizierungsfehler: {e}. Bitte API-Schlüssel prüfen.")
            self.markets = None
        except ccxt.NetworkError as e:
            logger.warning(f"WARNUNG: Netzwerkfehler beim Laden der Märkte: {e}.")
            self.markets = None
        except Exception as e:
            logger.warning(f"WARNUNG: Unerwarteter Fehler beim Laden der Märkte: {e}")
            self.markets = None

    # --- HILFSFUNKTIONEN (Unverändert) ---
    def fetch_recent_ohlcv(self, symbol, timeframe, limit=100):
        if not self.markets: return pd.DataFrame()
        try:
            effective_limit = min(limit, 1000)
            data = self.exchange.fetch_ohlcv(symbol, timeframe, limit=effective_limit)
            if not data: return pd.DataFrame()
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            return df
        except Exception as e:
            logger.error(f"Fehler bei fetch_recent_ohlcv für {symbol}: {e}")
            return pd.DataFrame()

    def fetch_historical_ohlcv(self, symbol, timeframe, start_date_str, end_date_str, max_retries=3):
        # ... (Implementierung wie im Originalcode)
        if not self.markets: return pd.DataFrame()
        try:
            start_dt = pd.to_datetime(start_date_str + 'T00:00:00Z', utc=True)
            end_dt = pd.to_datetime(end_date_str + 'T23:59:59Z', utc=True)
            start_ts = int(start_dt.timestamp() * 1000)
            end_ts = int(end_dt.timestamp() * 1000)
        except ValueError as e:
            logger.error(f"FEHLER: Ungültiges Datumsformat: {e}")
            return pd.DataFrame()

        all_ohlcv = []
        current_ts = start_ts
        retries = 0
        limit = 1000
        timeframe_duration_ms = self.exchange.parse_timeframe(timeframe) * 1000 if self.exchange.parse_timeframe(timeframe) else 60000

        while current_ts < end_ts and retries < max_retries:
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=current_ts, limit=limit)
                if not ohlcv:
                    logger.warning(f"Keine OHLCV-Daten für {symbol} {timeframe} ab {pd.to_datetime(current_ts, unit='ms', utc=True)} erhalten.")
                    current_ts += limit * timeframe_duration_ms
                    continue

                ohlcv = [candle for candle in ohlcv if candle[0] <= end_ts]
                if not ohlcv: break

                all_ohlcv.extend(ohlcv)
                last_ts = ohlcv[-1][0]

                if last_ts >= current_ts:
                    current_ts = last_ts + timeframe_duration_ms
                else:
                    logger.warning("WARNUNG: Kein Zeitfortschritt beim Datenabruf, breche ab.")
                    break
                retries = 0
            except (ccxt.RateLimitExceeded, ccxt.NetworkError) as e:
                logger.warning(f"Netzwerk/Ratelimit-Fehler bei fetch_historical_ohlcv: {e}. Versuch {retries+1}/{max_retries}. Warte...")
                time.sleep(5 * (retries + 1))
                retries += 1
            except ccxt.BadSymbol as e:
                logger.error(f"FEHLER: Ungültiges Symbol bei fetch_historical_ohlcv: {symbol}. {e}")
                return pd.DataFrame()
            except Exception as e:
                logger.error(f"Unerwarteter Fehler bei fetch_historical_ohlcv: {e}. Versuch {retries+1}/{max_retries}.")
                time.sleep(5)
                retries += 1

        if not all_ohlcv:
            logger.warning(f"Keine historischen Daten für {symbol} ({timeframe}) im Zeitraum {start_date_str} - {end_date_str} gefunden.")
            return pd.DataFrame()

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='first')].sort_index()
        return df.loc[start_dt:end_dt]


    def fetch_ticker(self, symbol):
        if not self.markets: return None
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Fehler bei fetch_ticker für {symbol}: {e}")
            return None

    def set_margin_mode(self, symbol, mode='isolated'):
        if not self.markets: return False
        try:
            # Bitget V2 erwartet oft eine Angabe für productType
            params = {'productType': 'USDT-FUTURES'} 
            self.exchange.set_margin_mode(mode, symbol, params=params)
            return True
        except Exception as e:
            if 'Margin mode is the same' not in str(e) and 'margin mode is not modified' not in str(e).lower():
                logger.warning(f"Warnung: Margin-Modus konnte nicht gesetzt werden: {e}")
                return False
            return True

    def set_leverage(self, symbol, level=10):
        if not self.markets: return False
        try:
            params = {'productType': 'USDT-FUTURES'}
            self.exchange.set_leverage(level, symbol, params=params)
            return True
        except Exception as e:
            if 'Leverage not changed' not in str(e) and 'leverage is not modified' not in str(e).lower():
                logger.warning(f"Warnung: Set leverage failed: {e}")
                return False
            return True

    def create_market_order(self, symbol, side, amount, params={}):
        if not self.markets: return None
        try:
            order_params = {**params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES'
            rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
            if rounded_amount <= 0:
                logger.error(f"FEHLER: Berechneter Order-Betrag ist Null oder negativ ({rounded_amount}).")
                return None
            order = self.exchange.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            return order
        except ccxt.InsufficientFunds as e:
            logger.error(f"FEHLER: Nicht genügend Guthaben (InsufficientFunds): {e}")
            raise e
        except Exception as e:
            logger.error(f"FEHLER beim Erstellen der Market Order ({symbol}, {side}, {amount}): {e}")
            return None

    def place_trigger_market_order(self, symbol, side, amount, trigger_price, params={}):
        """Platziert eine Standard Trigger-Order (Stop-Loss oder Take-Profit)."""
        if not self.markets: return None
        try:
            rounded_price = float(self.exchange.price_to_precision(symbol, trigger_price))
            rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
            if rounded_amount <= 0:
                logger.error(f"FEHLER: Berechneter Trigger-Order-Betrag ist Null ({rounded_amount}).")
                return None

            order_params = {
                'triggerPrice': rounded_price,
                'reduceOnly': params.get('reduceOnly', False),
                'productType': 'USDT-FUTURES' 
            }
            order_params.update(params)
            
            # Wichtig für Bitget: Setzen des Plan-Typs für Trigger/Stop-Orders
            # Dies ist die JaegerBot Logik für Trigger (nicht TSL)
            order_params['planType'] = 'Plan' 
            order_params['stopLossTriggerPriceType'] = 'market_price'
            order_params['takeProfitTriggerPriceType'] = 'market_price'
            order_params['stopLossOrderType'] = 'market'
            order_params['takeProfitOrderType'] = 'market'

            logger.info(f"Sende Trigger Order: Side={side}, Amount={rounded_amount}, Params={order_params}")
            # ccxt V2 Bitget: Trigger orders MÜSSEN über create_order gesendet werden
            return self.exchange.create_order(symbol, 'market', side, rounded_amount, params=order_params)

        except Exception as e:
            logger.error(f"FEHLER beim Platzieren der Trigger Order ({symbol}, {side}, Params={order_params}): {e}", exc_info=True)
            return None

    # --- START KORREKTUR: Atomarer Order-Aufruf (TitanBot-Stil) ---
    def create_order_atomic(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str):
        """
        Erstellt Market Order mit integriertem SL und TP in einem atomaren API-Aufruf.
        Dieser Aufruf ist stabil und schließt TSL aus.
        """
        logger.info(f"[{symbol}] Starte atomare Order: {side}, Menge={amount}, SL={sl_price}, TP={tp_price}")
        
        # ccxt rundet den Betrag
        rounded_amount = float(self.exchange.amount_to_precision(symbol, amount))
        if rounded_amount <= 0:
            logger.error(f"FEHLER: Berechneter Order-Betrag ist Null oder negativ ({rounded_amount}).")
            raise ValueError("Order-Betrag zu klein oder negativ.")

        # Bestimme Order-Richtung für SL/TP-Parameter
        stop_loss_side = 'sell' if side == 'buy' else 'buy'
        take_profit_side = 'sell' if side == 'buy' else 'buy'
        
        # Wichtig: Bitget V2 benötigt spezifische Parameter für atomare SL/TP
        order_params = {
            'posSide': 'net',         # Für One-Way Mode (obligatorisch)
            'tradeSide': 'open',      # Zum Öffnen der Position (obligatorisch)
            'marginMode': margin_mode, 
            'productType': 'USDT-FUTURES',
            
            # Atomare SL/TP Parameter (JaegerBot/TitanBot-Stil für Bitget)
            'stopLossPrice': float(self.exchange.price_to_precision(symbol, sl_price)),
            'stopLossTriggerPrice': float(self.exchange.price_to_precision(symbol, sl_price)), # In V2 wird oft der Trigger-Preis benötigt
            'stopLossTriggerPriceType': 'market_price', 
            'stopLossOrderType': 'market',
            'stopLossSide': stop_loss_side,
            
            'takeProfitPrice': float(self.exchange.price_to_precision(symbol, tp_price)),
            'takeProfitTriggerPrice': float(self.exchange.price_to_precision(symbol, tp_price)),
            'takeProfitTriggerPriceType': 'market_price', 
            'takeProfitOrderType': 'market',
            'takeProfitSide': take_profit_side,
        }

        try:
            logger.info(f"[{symbol}] Sende ATOMARE Market-Order. Params: {order_params}")
            order = self.exchange.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            
            # Rückgabewerte für main.py anpassen
            order['average'] = order.get('average') or order.get('price') 
            order['filled'] = rounded_amount
            
            return order
        except Exception as e:
            logger.error(f"[{symbol}] FEHLER BEI ATOMARER ORDER: {e}", exc_info=True)
            raise

    # Wrapper für main.py, der den atomaren Aufruf verwendet (TSL ignoriert).
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str,
                                      tsl_config: dict = None):
        """Wrapper für main.py, der den atomaren Aufruf verwendet (TSL ignoriert)."""
        return self.create_order_atomic(symbol, side, amount, sl_price, tp_price, margin_mode)
