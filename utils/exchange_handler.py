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

    # --- Standard-Funktionen (leicht angepasst) ---
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
            balance = self.session.fetch_balance()
            # Prüft verschiedene mögliche Strukturen der Balance-Antwort
            if 'USDT' in balance and 'free' in balance['USDT']:
                return float(balance['USDT']['free'])
            elif 'free' in balance and 'USDT' in balance['free']: # Alternative Struktur
                return float(balance['free']['USDT'])
            elif 'total' in balance and 'USDT' in balance['total']: # Manchmal ist nur 'total' verfügbar
                # Hier nehmen wir 'total' als Annäherung, wenn 'free' nicht da ist
                logger.warning("Konnte 'free' USDT-Balance nicht finden, verwende 'total' als Fallback.")
                return float(balance['total']['USDT'])
            else:
                logger.warning("Kein USDT-Guthaben in der Balance-Antwort gefunden.")
                return 0.0
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des USDT-Guthabens: {e}", exc_info=True)
            # Im Fehlerfall 0 zurückgeben, um riskante Trades zu verhindern
            return 0.0

    # --- Positions- und Order-Management (Kernlogik von JaegerBot) ---

    def fetch_open_positions(self, symbol: str):
        """ Holt alle offenen Positionen für ein Symbol. """
        try:
            positions = self.session.fetch_positions([symbol])
            # Filtert nach Positionen, die tatsächlich eine Größe haben
            open_positions = [p for p in positions if p.get('contracts') is not None and float(p['contracts']) > 0]
            return open_positions
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Positionen: {e}", exc_info=True)
            raise # Wichtig, dass der Bot im Fehlerfall stoppt

    def fetch_open_trigger_orders(self, symbol: str):
        """ Ruft alle offenen Trigger-Orders (SL/TP) für ein Symbol ab (JaegerBot-Methode). """
        try:
            # Verwendet den 'stop'-Parameter, der oft für Trigger-Orders steht
            return self.session.fetch_open_orders(symbol, params={'stop': True})
        except Exception as e:
            logger.error(f"[{symbol}] Fehler beim Abrufen offener Trigger-Orders: {e}", exc_info=True)
            return [] # Im Fehlerfall leere Liste zurückgeben, um Abbruch zu vermeiden

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
                        # Wichtig: Explizit 'stop: True' mitgeben, falls die API es braucht
                        self.session.cancel_order(order['id'], symbol, params={'stop': True})
                        cancelled_count += 1
                        logger.info(f"[{symbol}] Trigger-Order {order['id']} storniert.")
                    except ccxt.OrderNotFound:
                        logger.info(f"[{symbol}] Trigger-Order {order['id']} war bereits geschlossen/storniert.")
                    except Exception as e_cancel_trigger:
                        logger.error(f"[{symbol}] Konnte Trigger-Order {order['id']} nicht stornieren: {e_cancel_trigger}")
            else:
                logger.info(f"[{symbol}] Housekeeper: Keine offenen Trigger-Orders gefunden.")

            # 2. Normale (Limit-) Orders stornieren (falls vorhanden)
            # Annahme: utbot2 verwendet nur Market/Trigger, aber sicherheitshalber prüfen.
            normal_orders = self.session.fetch_open_orders(symbol, params={'stop': False})
            if normal_orders:
                logger.info(f"[{symbol}] Housekeeper: {len(normal_orders)} offene normale Order(s) gefunden. Storniere...")
                for order in normal_orders:
                    try:
                        self.session.cancel_order(order['id'], symbol)
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
            # Im Fehlerfall keine Anzahl zurückgeben oder Exception weiterleiten?
            # Wir geben 0 zurück, um den Ablauf nicht zu blockieren, aber der Fehler wird geloggt.
            return 0

        if cancelled_count > 0:
            logger.info(f"[{symbol}] Housekeeper: Insgesamt {cancelled_count} Order(s) storniert.")
        return cancelled_count


    # --- Order Platzierung (Kombination aus utbot2 Bedarf & JaegerBot Logik) ---

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        """ Setzt Hebel und Margin-Modus (von utbot2 übernommen, leicht angepasst). """
        # Stellt sicher, dass der Hebel ein Integer ist
        leverage = int(round(leverage))
        if leverage < 1: leverage = 1 # Mindestens 1x Hebel

        try:
            # 1. Margin-Modus setzen (versuchen)
            try:
                # ccxt Standardmethode
                self.session.set_margin_mode(margin_mode.lower(), symbol)
                logger.info(f"[{symbol}] Margin-Modus erfolgreich auf '{margin_mode.lower()}' gesetzt.")
            except ccxt.NotSupported:
                logger.warning(f"[{symbol}] Exchange unterstützt set_margin_mode nicht explizit. Versuche über Parameter.")
                # Hier könnten spezifische Parameter für Bitget nötig sein, falls set_margin_mode nicht geht
            except Exception as e_margin:
                # Ignoriere Fehler, wenn Modus schon korrekt ist
                if 'Margin mode is the same' not in str(e_margin):
                    logger.warning(f"[{symbol}] Setzen des Margin-Modus fehlgeschlagen (ignoriert wenn bereits korrekt): {e_margin}")

            # 2. Hebel setzen
            # Bitget erfordert oft 'holdSide' für isolated margin
            params = {}
            if margin_mode.lower() == 'isolated':
                # HINWEIS: 'posSide': 'net' wurde entfernt, da es in ccxt 4.3.5 nicht benötigt/unterstützt wird
                params = {'holdSide': 'long'}
                try:
                    self.session.set_leverage(leverage, symbol, params=params)
                    params = {'holdSide': 'short'}
                    self.session.set_leverage(leverage, symbol, params=params)
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x für Long & Short (Isolated) gesetzt.")
                except Exception as e_lev_iso:
                    # Ignoriere 'Leverage not changed' Fehler
                    if 'Leverage not changed' not in str(e_lev_iso) and 'repeat submit' not in str(e_lev_iso):
                        logger.error(f"[{symbol}] Fehler beim Setzen des Isolated Hebels: {e_lev_iso}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Isolated) gesetzt.")

            else: # Cross Margin
                try:
                    self.session.set_leverage(leverage, symbol)
                    logger.info(f"[{symbol}] Hebel erfolgreich auf {leverage}x (Cross) gesetzt.")
                except Exception as e_lev_cross:
                    if 'Leverage not changed' not in str(e_lev_cross) and 'repeat submit' not in str(e_lev_cross):
                        logger.error(f"[{symbol}] Fehler beim Setzen des Cross Hebels: {e_lev_cross}"); raise
                    else:
                        logger.info(f"[{symbol}] Hebel war bereits auf {leverage}x (Cross) gesetzt.")

        except Exception as e_general:
            logger.error(f"[{symbol}] Unerwarteter Fehler beim Setzen von Hebel/Margin: {e_general}", exc_info=True)
            raise # Im Zweifel abbrechen


    def create_market_order(self, symbol: str, side: str, amount: float, params: dict = {}):
        """ Erstellt eine reine Market-Order (von JaegerBot übernommen). """
        try:
            # Füge Bitget-spezifischen Order-Typ hinzu, falls nötig (oft 'market' oder spezifischer)
            # params['type'] = 'market' # redundant, da in create_order spezifiziert
            logger.info(f"[{symbol}] Sende Market-Order: Seite={side}, Menge={amount}, Params={params}")
            order = self.session.create_order(symbol, 'market', side, amount, params=params)
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
        """ Platziert eine SL- oder TP-Order als Trigger-Market-Order (JaegerBot-Methode). """
        try:
            # Runde den Preis auf die von der Exchange erlaubte Präzision
            rounded_price = float(self.session.price_to_precision(symbol, trigger_price))

            # Füge 'stopPrice' hinzu (wird von ccxt oft in triggerPrice umgewandelt)
            # 'reduceOnly' ist entscheidend für SL/TP
            order_params = {
                'stopPrice': rounded_price,
                'reduceOnly': True, # WICHTIG: Nur Position schließen, keine neue eröffnen
                # HINWEIS: 'posSide': 'net' wurde entfernt
                **params # Übernimmt zusätzliche Parameter
            }

            logger.info(f"[{symbol}] Sende Trigger-Market-Order: Seite={side}, Menge={amount}, Trigger@{rounded_price}, Params={order_params}")

            # Verwende 'market' als Typ, da es eine Market-Order ist, die durch stopPrice ausgelöst wird
            order = self.session.create_order(symbol, 'market', side, amount, params=order_params)

            logger.info(f"[{symbol}] Trigger-Market-Order erfolgreich platziert. ID: {order.get('id')}")
            return order

        except ccxt.ExchangeError as e:
            # Spezifische Fehlerbehandlung für Bitget könnte hier nötig sein
            logger.error(f"[{symbol}] Exchange-Fehler bei Trigger-Order: {e}")
            raise
        except Exception as e:
            logger.error(f"[{symbol}] Unerwarteter Fehler bei Trigger-Order: {e}", exc_info=True)
            raise


    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float, margin_mode: str):
        """
        Führt den robusten 3-Schritt-Prozess zur Trade-Eröffnung aus (JaegerBot-Logik).
        1. Market-Order (Einstieg)
        2. Trigger-Order (Stop-Loss) mit reduceOnly
        3. Trigger-Order (Take-Profit) mit reduceOnly
        """
        logger.info(f"[{symbol}] Starte 3-Schritt Order-Platzierung: {side}, Menge={amount}, SL={sl_price}, TP={tp_price}")

        # 1. Market-Order (Einstieg)
        try:
            # KORREKTUR: Wir senden NUR 'marginMode', genau wie JaegerBot es tut.
            # 'posSide' wurde entfernt.
            market_params = {
                'marginMode': margin_mode.lower()
            }
            market_order = self.create_market_order(symbol, side, amount, params=market_params)
            
            entry_price = market_order.get('price') or market_order.get('average') or self.fetch_ticker(symbol)['last'] # Bestimme den Einstiegspreis
            logger.info(f"[{symbol}] Schritt 1/3: ✅ Market-Order platziert. ID: {market_order['id']}, Geschätzter Entry: {entry_price}")
        except Exception as e:
            logger.error(f"[{symbol}] ❌ SCHRITT 1 FEHLGESCHLAGEN: Market-Order fehlgeschlagen: {e}. Breche Trade ab.")
            # Kein Housekeeping nötig, da keine Position eröffnet wurde
            raise # Fehler weiterleiten, um den Trade-Versuch zu stoppen

        # Kurze Pause, damit die Position bei der Exchange registriert wird
        time.sleep(3) # 3 Sekunden sollten sicher sein

        # Hole die tatsächliche Positionsgröße (wichtig für SL/TP)
        try:
            final_position = self.fetch_open_positions(symbol)
            if not final_position:
                # Manchmal dauert es länger oder die Order wurde nur teilweise gefüllt
                logger.warning(f"[{symbol}] Position nach Market-Order nicht sofort gefunden. Versuche erneut in 5s...")
                time.sleep(5)
                final_position = self.fetch_open_positions(symbol)
                if not final_position:
                    raise Exception(f"Position konnte nach Market-Order ID {market_order['id']} nicht bestätigt werden. Manuelle Prüfung erforderlich!")

            # Nehme die erste gefundene Position (sollte nur eine sein)
            final_amount = float(final_position[0]['contracts'])
            actual_entry_price = float(final_position[0]['entryPrice'])
            logger.info(f"[{symbol}] Position bestätigt: Menge={final_amount}, Exakter Entry={actual_entry_price}")

        except Exception as e:
            logger.error(f"[{symbol}] ❌ KRITISCH: Konnte Position nach Market-Order nicht bestätigen: {e}. Position ist offen aber UNGESCHÜTZT! Versuche Housekeeping.")
            self.cleanup_all_open_orders(symbol) # Versuche SL/TP zu löschen, falls welche platziert wurden
            # Hier könnte man versuchen, die offene Position per Market-Order zu schließen, ist aber riskant.
            # Besser: Fehler weiterleiten und manuellen Eingriff erfordern.
            raise Exception(f"Positionsbestätigung fehlgeschlagen, SL/TP nicht platziert! Manuelle Prüfung für {symbol} nötig.") from e


        # 2. Definiere die Schließungs-Richtung und platziere SL/TP
        close_side = 'sell' if side == 'buy' else 'buy'
        sl_success = False
        tp_success = False

        # 3. Stop-Loss (Trigger-Order mit reduceOnly)
        try:
            logger.info(f"[{symbol}] Schritt 2/3: Platziere Stop-Loss ({close_side}) bei {sl_price} für Menge {final_amount}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, sl_price) # reduceOnly ist in place_trigger_market_order Standard
            sl_success = True
            logger.info(f"[{symbol}] Schritt 2/3: ✅ Stop-Loss platziert.")
        except Exception as e_sl:
            logger.error(f"[{symbol}] ❌ KRITISCH: SL-Order fehlgeschlagen: {e_sl}. Position ist UNGESCHÜTZT!")
            # Nicht abbrechen, TP trotzdem versuchen

        # 4. Take-Profit (Trigger-Order mit reduceOnly)
        try:
            logger.info(f"[{symbol}] Schritt 3/3: Platziere Take-Profit ({close_side}) bei {tp_price} für Menge {final_amount}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, tp_price)
            tp_success = True
            logger.info(f"[{symbol}] Schritt 3/3: ✅ Take-Profit platziert.")
        except Exception as e_tp:
            logger.error(f"[{symbol}] ❌ WARNUNG: TP-Order fehlgeschlagen: {e_tp}.")
            # Wenn SL erfolgreich war, ist die Position zumindest geschützt.

        # 5. Gebe die ursprüngliche Market-Order zurück (enthält ID und Timestamp)
        # Füge den tatsächlichen Einstiegspreis hinzu, falls verfügbar
        market_order['average'] = actual_entry_price
        market_order['filled'] = final_amount # Füge die tatsächliche Menge hinzu
        return market_order
