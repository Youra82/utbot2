# utbot2/utils/exchange_handler.py (Inspiriert von JaegerBot)
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime, timezone # Import hinzugefügt

logger = logging.getLogger('utbot2') # Logger-Namen angepasst

class ExchangeHandler:
    def __init__(self, api_setup=None):
        if api_setup:
            # Verwende explizit Bitget
            self.session = ccxt.bitget({
                'apiKey': api_setup['apiKey'], 'secret': api_setup['secret'], 'password': api_setup['password'],
                'options': { 'defaultType': 'swap' },
            })
        else:
            self.session = ccxt.bitget({'options': { 'defaultType': 'swap' }})
        self.markets = self.session.load_markets()
        logger.info("ExchangeHandler initialisiert und Märkte geladen.")

    # --- Standard-Funktionen (unverändert) ---
    def fetch_ohlcv(self, symbol, timeframe, limit):
        """ Lädt die letzten 'limit' Kerzen. """
        try:
            # Bitget (und viele andere) erwarten 'limit', nicht 'since' für die letzten Kerzen
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                logger.warning(f"[{symbol}] Keine OHLCV-Daten erhalten.")
                return pd.DataFrame()

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            # Stelle sicher, dass die benötigten Spalten numerisch sind
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Laden der Kerzendaten: {e}", exc_info=True)
            raise

    def fetch_ticker(self, symbol):
        """ Holt den aktuellen Ticker (Preisinformationen). """
        try:
            return self.session.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen des Tickers: {e}", exc_info=True)
            raise

    def fetch_balance_usdt(self):
        """ Holt das verfügbare USDT-Guthaben (robuste Version von JaegerBot). """
        try:
            # --- KORREKTUR: 'productType' hinzufügen, um nur Futures-Guthaben abzurufen ---
            params = {'productType': 'USDT-FUTURES'}
            balance = self.session.fetch_balance(params=params)
            # --- ENDE KORREKTUR ---

            # Prüft verschiedene mögliche Strukturen der Balance-Antwort
            if 'USDT' in balance and 'free' in balance['USDT']:
                return float(balance['USDT']['free'])
            elif 'free' in balance and 'USDT' in balance['free']: # Alternative Struktur
                return float(balance['free']['USDT'])
            
            # --- KORREKTUR: TitanBot-Logik für Unified/Classic Account Fallback ---
            elif 'info' in balance and 'data' in balance['info'] and isinstance(balance['info']['data'], list):
                for asset_info in balance['info']['data']:
                    if asset_info.get('marginCoin') == 'USDT':
                        if 'available' in asset_info and asset_info['available'] is not None:
                            return float(asset_info['available'])
                        elif 'equity' in asset_info and asset_info['equity'] is not None:
                             # Equity ist das Gesamtkapital, 'available' (free) ist besser
                            logger.warning("Verwende 'equity' als Fallback für Guthaben.")
                            return float(asset_info['equity'])
            # --- ENDE KORREKTUR ---
            
            elif 'total' in balance and 'USDT' in balance['total']: # Letzter Fallback
                logger.warning("Konnte 'free' USDT-Balance nicht finden, verwende 'total' als Fallback.")
                return float(balance['total']['USDT'])
            else:
                logger.warning(f"Kein USDT-Guthaben in der Balance-Antwort gefunden. Struktur: {balance}")
                return 0.0
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des USDT-Guthabens: {e}", exc_info=True)
            return 0.0

    # -----------------------------------------------------------------
    # --- START KORREKTUR (fetch_open_positions) ---
    # -----------------------------------------------------------------
    def fetch_open_positions(self, symbol: str):
        """ Holt alle offenen Positionen für ein Symbol (TitanBot-Logik). """
        try:
            # WICHTIG: Spezifiziere 'USDT-FUTURES'
            params = {'productType': 'USDT-FUTURES'}
            positions = self.session.fetch_positions([symbol], params=params)
            
            # Filtert nach Positionen, die tatsächlich eine Größe haben (robuste Prüfung)
            open_positions = []
            for p in positions:
                try:
                    contracts_str = p.get('contracts')
                    # Verwende abs() > 1e-9 für eine robuste Prüfung statt > 0
                    if contracts_str is not None and abs(float(contracts_str)) > 1e-9:
                        open_positions.append(p)
                except (ValueError, TypeError) as e:
                    logger.warning(f"[{symbol}] Ungültiger 'contracts'-Wert in Positionsdaten: {contracts_str}. Fehler: {e}")
                    continue
            return open_positions
            
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Positionen: {e}", exc_info=True)
            raise # Wichtig, dass der Bot im Fehlerfall stoppt
    # -----------------------------------------------------------------
    # --- ENDE KORREKTUR ---
    # -----------------------------------------------------------------

    def fetch_open_trigger_orders(self, symbol: str):
        """ Ruft alle offenen Trigger-Orders (SL/TP) für ein Symbol ab (JaegerBot-Methode). """
        try:
            # --- KORREKTUR: 'productType' hinzufügen ---
            params = {'stop': True, 'productType': 'USDT-FUTURES'}
            return self.session.fetch_open_orders(symbol, params=params)
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Trigger-Orders: {e}", exc_info=True)
            return [] 

    def cleanup_all_open_orders(self, symbol: str):
        """ Storniert ALLE offenen Orders (Trigger und Normal) für ein Symbol (JaegerBot's Housekeeper). """
        cancelled_count = 0
        try:
            # 1. Trigger-Orders stornieren
            trigger_orders = self.fetch_open_trigger_orders(symbol)
            if trigger_orders:
                logger.info(f"[{symbol}] Housekeeper: {len(trigger_orders)} offene Trigger-Order(s) gefunden. Storniere...")
                for order in trigger_orders:
                    try:
                        # --- KORREKTUR: 'productType' hinzufügen ---
                        self.session.cancel_order(order['id'], symbol, params={'stop': True, 'productType': 'USDT-FUTURES'})
                        cancelled_count += 1
                        logger.info(f"[{symbol}] Trigger-Order {order['id']} storniert.")
                    except ccxt.OrderNotFound:
                        logger.info(f"[{symbol}] Trigger-Order {order['id']} war bereits geschlossen/storniert.")
                    except Exception as e_cancel_trigger:
                        logger.error(f"[{symbol}] Konnte Trigger-Order {order['id']} nicht stornieren: {e_cancel_trigger}")
            else:
                logger.info(f"[{symbol}] Housekeeper: Keine offenen Trigger-Orders gefunden.")

            # 2. Normale (Limit-) Orders stornieren (falls vorhanden)
            # --- KORREKTUR: 'productType' hinzufügen ---
            normal_orders = self.session.fetch_open_orders(symbol, params={'stop': False, 'productType': 'USDT-FUTURES'})
            if normal_orders:
                logger.info(f"[{symbol}] Housekeeper: {len(normal_orders)} offene normale Order(s) gefunden. Storniere...")
                for order in normal_orders:
                    try:
                        self.session.cancel_order(order['id'], symbol, params={'productType': 'USDT-FUTURES'})
                        cancelled_count += 1
                        logger.info(f"[{symbol}] Normale Order {order['id']} storniert.")
                    except ccxt.OrderNotFound:
                        logger.info(f"[{symbol}] Normale Order {order['id']} war bereits geschlossen/storniert.")
                    except Exception as e_cancel_normal:
                        logger.error(f"[{symbol}] Konnte normale Order {order['id']} nicht stornieren: {e_cancel_normal}")
            else:
                logger.info(f"[{symbol}] Housekeeper: Keine offenen normalen Orders gefunden.")

        except Exception as e_fetch:
            logger.error(f"[{symbol}] Kritischer Fehler im Housekeeper beim Abrufen von Orders: {e_fetch}", exc_info=True)
            return 0

        if cancelled_count > 0:
            logger.info(f"[{symbol}] Housekeeper: Insgesamt {cancelled_count} Order(s) storniert.")
        return cancelled_count


    # --- Order Platzierung (Kernlogik von JaegerBot) ---

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        """ Setzt Hebel und Margin-Modus (unverändert). """
        leverage = int(round(leverage))
        if leverage < 1: leverage = 1 
        try:
            try:
                self.session.set_margin_mode(margin_mode.lower(), symbol)
                logger.info(f"[{symbol}] Margin-Modus erfolgreich auf '{margin_mode.lower()}' gesetzt.")
            except ccxt.NotSupported:
                logger.warning(f"[{symbol}] Exchange unterstützt set_margin_mode nicht explizit. Versuche über Parameter.")
            except Exception as e_margin:
                if 'Margin mode is the same' not in str(e_margin):
                    logger.warning(f"[{symbol}] Setzen des Margin-Modus fehlgeschlagen (ignoriert wenn bereits korrekt): {e_margin}")

            params = {}
            if margin_mode.lower() == 'isolated':
                params = {'holdSide': 'long', 'posSide': 'net'}
                try:
                    self.session.set_leverage(leverage, symbol, params=params)
                    params = {'holdSide': 'short', 'posSide': 'net'}
                    self.session.set_leverage(leverage, symbol, params=params)
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x für Long & Short (Isolated) gesetzt.")
                except Exception as e_lev_iso:
                    if 'Leverage not changed' not in str(e_lev_iso) and 'repeat submit' not in str(e_lev_iso):
                        logger.error(f"[{symbol}] Fehler beim Setzen des Isolated Hebels: {e_lev_iso}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Isolated) gesetzt.")
            else: # Cross Margin
                try:
                    self.session.set_leverage(leverage, symbol, params={'posSide': 'net'})
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x (Cross) gesetzt.")
                except Exception as e_lev_cross:
                    if 'Leverage not changed' not in str(e_lev_cross) and 'repeat submit' not in str(e_lev_cross):
                        logger.error(f"[{symbol}] Fehler beim Setzen des Cross Hebels: {e_lev_cross}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Cross) gesetzt.")
        except Exception as e_general:
            logger.error(f"[{symbol}] Unerwarteter Fehler beim Setzen von Hebel/Margin: {e_general}", exc_info=True)
            raise

    def create_market_order(self, symbol: str, side: str, amount: float, params: dict = {}):
        """ 
        Erstellt eine reine Market-Order (MIT TITANBOT-LOGIK).
        Fügt 'productType' hinzu und rundet den Betrag.
        """
        try:
            order_params = {**params}
            if 'productType' not in order_params:
                order_params['productType'] = 'USDT-FUTURES' 
            
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
            logger.error(f"[{symbol}] Exchange-Fehler bei Market-Order: {e}")
            raise
        except Exception as e:
            logger.error(f"[{symbol}] Unerwarteter Fehler bei Market-Order: {e}", exc_info=True)
            raise

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
                'posSide': 'net',
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
