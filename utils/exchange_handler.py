# utbot2/utils/exchange_handler.py (Version 3.9 - Korrigiert für 40774 & 400172)
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime, timezone

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
        """Holt das verfügbare USDT-Guthaben (robuste Version)."""
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
                        elif 'equity' in asset_info and asset_info['equity'] is not None and usdt_balance == 0.0:
                                logger.warning("Verwende 'equity' als Fallback für Guthaben.")
                                usdt_balance = float(asset_info['equity'])
            elif 'free' in balance and 'USDT' in balance['free']:
                 usdt_balance = float(balance['free']['USDT'])
            elif 'total' in balance and 'USDT' in balance['total'] and usdt_balance == 0.0:
                logger.warning("Konnte 'free' USDT-Balance nicht finden, verwende 'total' als Fallback.")
                usdt_balance = float(balance['total']['USDT'])

            if usdt_balance == 0.0:
                logger.warning(f"Kein USDT-Guthaben in der Balance-Antwort gefunden.")

            return usdt_balance
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des USDT-Guthabens: {e}", exc_info=True)
            return 0.0

    def fetch_open_positions(self, symbol: str):
        """Holt alle offenen Positionen für ein Symbol (TitanBot-Logik)."""
        try:
            params = {'productType': 'USDT-FUTURES'}
            positions = self.session.fetch_positions([symbol], params=params)

            open_positions = []
            for p in positions:
                try:
                    contracts_str = p.get('contracts')
                    if contracts_str is not None and abs(float(contracts_str)) > 1e-9:
                        open_positions.append(p)
                except (ValueError, TypeError) as e:
                    logger.warning(f"[{symbol}] Ungültiger 'contracts'-Wert in Positionsdaten: {contracts_str}. Fehler: {e}")
                    continue
            return open_positions

        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Positionen: {e}", exc_info=True)
            raise

    def fetch_open_trigger_orders(self, symbol: str):
        """Ruft alle offenen Trigger-Orders (SL/TP) für ein Symbol ab."""
        try:
            params = {'stop': True, 'productType': 'USDT-FUTURES'}
            return self.session.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Trigger-Orders: {e}", exc_info=True)
            return []

    def cleanup_all_open_orders(self, symbol: str):
        """Storniert ALLE offenen Orders (Trigger und Normal) für ein Symbol."""
        cancelled_count = 0

        # 1. Normale Orders stornieren (stop: False)
        try:
            params_normal = {'productType': 'USDT-FUTURES', 'stop': False}
            self.session.cancel_all_orders(symbol, params=params_normal)
            cancelled_count += 1
            logger.info(f"[{symbol}] Housekeeper: 'cancel_all_orders' (Normal) gesendet.")
            time.sleep(0.5)
        except ccxt.ExchangeError as e:
            if 'Order not found' in str(e) or 'no order to cancel' in str(e).lower() or '22001' in str(e):
                logger.info(f"[{symbol}] Housekeeper: Keine normalen Orders zum Stornieren gefunden.")
            else:
                logger.error(f"[{symbol}] Housekeeper: Fehler beim Stornieren normaler Orders: {e}")
        except Exception as e:
            logger.error(f"[{symbol}] Housekeeper: Unerwarteter Fehler (Normal): {e}")

        # 2. Trigger Orders stornieren (stop: True)
        try:
            params_trigger = {'productType': 'USDT-FUTURES', 'stop': True}
            self.session.cancel_all_orders(symbol, params=params_trigger)
            cancelled_count += 1
            logger.info(f"[{symbol}] Housekeeper: 'cancel_all_orders' (Trigger) gesendet.")
            time.sleep(0.5)
        except ccxt.ExchangeError as e:
            if 'Order not found' in str(e) or 'no order to cancel' in str(e).lower() or '22001' in str(e):
                logger.info(f"[{symbol}] Housekeeper: Keine Trigger-Orders zum Stornieren gefunden.")
            else:
                logger.error(f"[{symbol}] Housekeeper: Fehler beim Stornieren von Trigger-Orders: {e}")
        except Exception as e:
            logger.error(f"[{symbol}] Housekeeper: Unerwarteter Fehler (Trigger): {e}")

        return cancelled_count


    # --- Order Platzierung (Kernlogik von JaegerBot) ---

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        """Setzt Hebel und Margin-Modus."""
        leverage = int(round(leverage))
        if leverage < 1: leverage = 1
        try:
            try:
                params_margin = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
                self.session.set_margin_mode(margin_mode.lower(), symbol, params=params_margin)
                logger.info(f"[{symbol}] Margin-Modus erfolgreich auf '{margin_mode.lower()}' gesetzt.")
            except ccxt.ExchangeError as e_margin:
                if 'Margin mode is the same' not in str(e_margin) and 'margin mode is not changed' not in str(e_margin).lower():
                    logger.warning(f"[{symbol}] Setzen des Margin-Modus fehlgeschlagen (ignoriert wenn bereits korrekt): {e_margin}")
            except ccxt.NotSupported:
                logger.warning(f"[{symbol}] Exchange unterstützt set_margin_mode nicht explizit.")

            params = {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'}
            if margin_mode.lower() == 'isolated':
                params_long = {**params, 'holdSide': 'long', 'posSide': 'net'}
                params_short = {**params, 'holdSide': 'short', 'posSide': 'net'}
                try:
                    self.session.set_leverage(leverage, symbol, params=params_long)
                    time.sleep(0.2)
                    self.session.set_leverage(leverage, symbol, params=params_short)
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x für Long & Short (Isolated) gesetzt.")
                except ccxt.ExchangeError as e_lev_iso:
                    if 'Leverage not changed' not in str(e_lev_iso) and 'leverage is not modified' not in str(e_lev_iso).lower():
                        logger.error(f"[{symbol}] Fehler beim Setzen des Isolated Hebels: {e_lev_iso}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Isolated) gesetzt.")
            else: # Cross Margin
                try:
                    params_cross = {**params, 'posSide': 'net'}
                    self.session.set_leverage(leverage, symbol, params=params_cross)
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x (Cross) gesetzt.")
                except ccxt.ExchangeError as e_lev_cross:
                    if 'Leverage not changed' not in str(e_lev_cross) and 'leverage is not modified' not in str(e_lev_cross).lower():
                        logger.error(f"[{symbol}] Fehler beim Setzen des Cross Hebels: {e_lev_cross}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Cross) gesetzt.")
        except Exception as e_general:
            logger.error(f"[{symbol}] Unerwarteter Fehler beim Setzen von Hebel/Margin: {e_general}", exc_info=True)
            raise

    # -----------------------------------------------------------------
    # --- START KORREKTUR (create_market_order) ---
    # -----------------------------------------------------------------
    def create_market_order(self, symbol: str, side: str, amount: float, params: dict = {}):
        """
        Erstellt eine reine Market-Order (MIT TITANBOT/STBOT-LOGIK).
        Fügt 'productType' hinzu und rundet den Betrag.
        ENTFERNT 'posSide', 'tradeSide' UND 'marginMode', wenn 'reduceOnly' verwendet wird.
        """
        try:
            order_params = {**params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES'

            # --- START KORREKTUR (Fehler 40774 / 400172) ---
            # Für "One-Way Mode" (unilateral) Konten MUSS posSide='net' IMMER
            # gesendet werden, sowohl beim Öffnen als auch beim Schließen.
            if 'posSide' not in order_params:
                order_params['posSide'] = 'net'
            
            is_reduce_only = str(order_params.get('reduceOnly', 'false')).lower() == 'true'

            if is_reduce_only:
                # 'tradeSide' (z.B. 'open') darf NICHT mit 'reduceOnly' gesendet werden.
                if 'tradeSide' in order_params:
                    logger.debug(f"Entferne 'tradeSide' aus reduceOnly-Order-Params.")
                    del order_params['tradeSide']
                
                # 'posSide' NICHT löschen, wird für One-Way Mode benötigt.
                
                # 'marginMode = None' (mein alter Fix) war FALSCH und verursachte Fehler 400172.
                # Wir lassen ccxt einfach den Standard-marginMode senden ('crossed'),
                # was in Kombination mit posSide='net' korrekt ist.
            # --- ENDE KORREKTUR ---

            rounded_amount = float(self.session.amount_to_precision(symbol, amount))
            if rounded_amount <= 0:
                  logger.error(f"FEHLER: Berechneter Order-Betrag ist Null oder negativ ({rounded_amount}).")
                  return None

            logger.info(f"[{symbol}] Sende Market-Order: Seite={side}, Menge={rounded_amount}, Params={order_params}")
            order = self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            logger.info(f"[{symbol}] Market-Order erfolgreich platziert. ID: {order.get('id')}")
            return order

        except ccxt.InsufficientFunds as e:
            logger.error(f"[{symbol}] Nicht genügend Guthaben für Market-Order: {e}")
            raise
        except ccxt.ExchangeError as e:
            # Fange "No position to close" ab
            if '22002' in str(e) or 'No position to close' in str(e).lower():
                logger.warning(f"[{symbol}] Keine Position zum Schließen (reduceOnly).")
                return None
            
            # --- NEU: Fange Fehler 40774 (One-Way-Mode-Konflikt) explizit ab, falls er erneut auftritt
            if '40774' in str(e) or 'unilateral position' in str(e):
                 logger.error(f"[{symbol}] Kritischer API-Konflikt (40774) im One-Way-Mode: {e}")
                 raise

            logger.error(f"[{symbol}] Exchange-Fehler bei Market-Order: {e}")
            raise
        except Exception as e:
            logger.error(f"[{symbol}] Unerwarteter Fehler bei Market-Order: {e}", exc_info=True)
            raise
    # -----------------------------------------------------------------
    # --- ENDE KORREKTUR (create_market_order) ---
    # -----------------------------------------------------------------

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, params: dict = {}):
        """
        Platziert eine SL- oder TP-Order als Trigger-Market-Order (TitanBot/JaegerBot-Logik).
        """
        try:
            rounded_price = float(self.session.price_to_precision(symbol, trigger_price))
            rounded_amount = float(self.session.amount_to_precision(symbol, amount))

            order_params = {
                'triggerPrice': rounded_price,
                'reduceOnly': True,
                'productType': 'USDT-FUTURES',
                **params
            }
            
            # --- START KORREKTUR (Fehler 40774 / 400172) ---
            # Auch Trigger-Orders (SL/TP) benötigen posSide='net' im One-Way-Mode.
            if 'posSide' not in order_params:
                order_params['posSide'] = 'net'
                
            # 'tradeSide' (z.B. 'open') darf NICHT mit 'reduceOnly' gesendet werden.
            if 'tradeSide' in order_params:
                del order_params['tradeSide']
            # --- ENDE KORREKTUR ---


            logger.info(f"[{symbol}] Sende Trigger-Market-Order: Seite={side}, Menge={rounded_amount}, Trigger@{rounded_price}, Params={order_params}")
            order = self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            logger.info(f"[{symbol}] Trigger-Market-Order erfolgreich platziert. ID: {order.get('id')}")
            return order

        except ccxt.ExchangeError as e:
            logger.error(f"[{symbol}] Exchange-Fehler bei Trigger-Order (TP/FixSL): {e}")
            raise
        except Exception as e:
            logger.error(f"[{symbol}] Unerwarteter Fehler bei Trigger-Order (TP/FixSL): {e}", exc_info=True)
            raise

    def place_trailing_stop_order(self, symbol, side, amount, activation_price, callback_rate_decimal, params={}):
        """
        Platziert eine Trailing Stop Market Order (Stop-Loss) (TitanBot/JaegerBot-Logik).
        :param callback_rate_decimal: Die Callback-Rate als Dezimalzahl (z.B. 0.01 für 1%)
        """
        if not self.markets: return None
        try:
            rounded_activation = float(self.session.price_to_precision(symbol, activation_price))
            rounded_amount = float(self.session.amount_to_precision(symbol, amount))
            if rounded_amount <= 0:
                logger.error(f"FEHLER: Berechneter TSL-Betrag ist Null ({rounded_amount}).")
                return None

            callback_rate_str = str(callback_rate_decimal * 100)

            order_params = {
                **params,
                'planType': 'trailing_stop',
                'triggerPrice': rounded_activation,
                'callbackRate': callback_rate_str,
                'triggerPriceType': 'market_price',
                'productType': 'USDT-FUTURES',
                'reduceOnly': True
            }

            # --- START KORREKTUR (Fehler 40774 / 400172) ---
            # Auch TSL-Orders benötigen posSide='net' im One-Way-Mode.
            if 'posSide' not in order_params:
                order_params['posSide'] = 'net'

            # 'tradeSide' (z.B. 'open') darf NICHT mit 'reduceOnly' gesendet werden.
            if 'tradeSide' in order_params:
                del order_params['tradeSide']
            
            # 'marginMode' nicht auf None setzen.
            # --- ENDE KORREKTUR ---

            logger.info(f"[{symbol}] Sende Trailing-Stop-Order: Seite={side}, Menge={rounded_amount}, Params={order_params}")
            order = self.session.create_order(symbol, 'market', side, rounded_amount, params=order_params)
            logger.info(f"[{symbol}] Trailing-Stop-Order erfolgreich platziert. ID: {order.get('id')}")
            return order

        except Exception as e:
            logger.error(f"[{symbol}] FEHLER beim Platzieren des Trailing Stop: {e} | Params: {order_params}", exc_info=True)
            raise

    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str,
                                      tsl_config: dict = None):
        """
        Führt den robusten 3-Schritt-Prozess zur Trade-Eröffnung aus (Unverändert).
        """
        logger.info(f"[{symbol}] Starte 3-Schritt Order-Platzierung: {side}, Menge={amount}, SL={sl_price}, TP={tp_price}")

        # 1. Market-Order (Einstieg)
        try:
            market_params = {
                'posSide': 'net', # 'net' ist korrekt für One-Way-Mode
                'tradeSide': 'open'
                # productType wird von create_market_order automatisch hinzugefügt
            }
            market_order = self.create_market_order(symbol, side, amount, params=market_params)

            entry_price = market_order.get('price') or market_order.get('average') or self.fetch_ticker(symbol)['last']
            logger.info(f"[{symbol}] Schritt 1/3: ✅ Market-Order platziert. ID: {market_order['id']}, Geschätzter Entry: {entry_price}")
        except Exception as e:
            logger.error(f"[{symbol}] ❌ SCHRITT 1 FEHLGESCHLAGEN: Market-Order fehlgeschlagen: {e}. Breche Trade ab.")
            raise

        time.sleep(3)

        # Hole die tatsächliche Positionsgröße (wichtig für SL/TP)
        try:
            final_position = self.fetch_open_positions(symbol)
            if not final_position:
                logger.warning(f"[{symbol}] Position nach Market-Order nicht sofort gefunden. Versuche erneut in 5s...")
                time.sleep(5)
                final_position = self.fetch_open_positions(symbol)
                if not final_position:
                    raise Exception(f"Position konnte nach Market-Order ID {market_order['id']} nicht bestätigt werden. Manuelle Prüfung erforderlich!")

            final_amount = float(final_position[0]['contracts'])
            actual_entry_price = float(final_position[0]['entryPrice'])
            logger.info(f"[{symbol}] Position bestätigt: Menge={final_amount}, Exakter Entry={actual_entry_price}")

        except Exception as e:
            logger.error(f"[{symbol}] ❌ KRITISCH: Konnte Position nach Market-Order nicht bestätigen: {e}. Position ist offen aber UNGESCHÜTZT! Versuche Housekeeping.")
            self.cleanup_all_open_orders(symbol)
            raise Exception(f"Positionsbestätigung fehlgeschlagen, SL/TP nicht platziert! Manuelle Prüfung für {symbol} nötig.") from e


        # 2. Definiere die Schließungs-Richtung und platziere SL/TP
        close_side = 'sell' if side == 'buy' else 'buy'
        sl_success = False
        tp_success = False

        trigger_params = {
            'reduceOnly': True,
            'productType': 'USDT-FUTURES'
            # posSide: 'net' wird von den place_... Funktionen hinzugefügt
        }

        # 3. Stop-Loss (Trigger-Order ODER TSL)
        try:
            if tsl_config and tsl_config.get('enabled', False):
                # --- A) TRAILING STOP WIRD VERWENDET ---
                callback_rate_pct_decimal = tsl_config.get('callback_pct', 1.0) / 100.0
                activation_margin_pct = tsl_config.get('activation_pct', 0.1) / 100.0

                if side == 'buy': # Long
                    activation_price = actual_entry_price * (1 + activation_margin_pct)
                else: # Short
                    activation_price = actual_entry_price * (1 - activation_margin_pct)

                if side == 'buy' and sl_price > activation_price:
                    logger.warning(f"[{symbol}] KI-SL ({sl_price}) ist über TSL-Aktivierung ({activation_price}). Verwende KI-SL als Aktivierung.")
                    activation_price = sl_price
                elif side == 'sell' and sl_price < activation_price:
                    logger.warning(f"[{symbol}] KI-SL ({sl_price}) ist unter TSL-Aktivierung ({activation_price}). Verwende KI-SL als Aktivierung.")
                    activation_price = sl_price

                logger.info(f"[{symbol}] Schritt 2/3: Platziere TRAILING Stop-Loss ({close_side})...")
                logger.info(f"[{symbol}] (Aktivierung: {activation_price:.4f}, Callback: {callback_rate_pct_decimal * 100.0}%)")

                self.place_trailing_stop_order(
                    symbol=symbol,
                    side=close_side,
                    amount=final_amount,
                    activation_price=activation_price,
                    callback_rate_decimal=callback_rate_pct_decimal,
                    params=trigger_params
                )
                sl_success = True
                logger.info(f"[{symbol}] Schritt 2/3: ✅ Trailing Stop-Loss platziert.")

            else:
                # --- B) FIXER STOP-LOSS WIRD VERWENDET (Alte Logik) ---
                logger.info(f"[{symbol}] Schritt 2/3: Platziere fixen Stop-Loss ({close_side}) bei {sl_price} für Menge {final_amount}...")
                self.place_trigger_market_order(symbol, close_side, final_amount, sl_price, params=trigger_params)
                sl_success = True
                logger.info(f"[{symbol}] Schritt 2/3: ✅ Fixen Stop-Loss platziert.")

        except Exception as e_sl:
            logger.error(f"[{symbol}] ❌ KRITISCH: SL-Order fehlgeschlagen: {e_sl}. Position ist UNGESCHÜTZT!")

        # 4. Take-Profit (Trigger-Order mit reduceOnly)
        try:
            logger.info(f"[{symbol}] Schritt 3/3: Platziere Take-Profit ({close_side}) bei {tp_price} für Menge {final_amount}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, tp_price, params=trigger_params)
            tp_success = True
            logger.info(f"[{symbol}] Schritt 3/3: ✅ Take-Profit platziert.")
        except Exception as e_tp:
            logger.error(f"[{symbol}] ❌ WARNUNG: TP-Order fehlgeschlagen: {e_tp}.")

        # 5. Gebe die ursprüngliche Market-Order zurück
        market_order['average'] = actual_entry_price
        market_order['filled'] = final_amount
        return market_order
