# utbot2/utils/exchange_handler.py (Version 3.9 - TSL auf Fix-SL umgestellt)
import ccxt
import logging
import pandas as pd
import time
from datetime import datetime, timezone

logger = logging.getLogger('utbot2')

class ExchangeHandler:
# ... (Rest des Codes von Zeile 11 bis 325 bleibt unverändert) ...

# --- Order Platzierung (Kernlogik von JaegerBot) ---

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        """Setzt Hebel und Margin-Modus."""
# ... (Rest des Codes von Zeile 160 bis 325 bleibt unverändert) ...
# ... (Die Funktionen fetch_ohlcv, fetch_ticker, fetch_balance_usdt, fetch_open_positions, fetch_open_trigger_orders, cleanup_all_open_orders, set_leverage, create_market_order, place_trigger_market_order, place_trailing_stop_order sind hier ausgelassen, da sie nicht geändert werden.)
    
    # Der korrigierte Code für place_trailing_stop_order muss NICHT mehr MovingPlan enthalten,
    # da wir diese Funktion bald umgehen. Wir behalten sie im Code, ändern aber den PlanType zurück,
    # da er keinen direkten API-Aufruf von ccxt generiert.
    def place_trailing_stop_order(self, symbol, side, amount, activation_price, callback_rate_decimal, params={}):
        """
        Platziert eine Trailing Stop Market Order (Stop-Loss) (TitanBot/JaegerBot-Logik).
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
                'planType': 'Plan', # Zurück zum generischen Plan, da MovingPlan / Trailing Stop über CCXT problematisch ist
                'triggerPrice': rounded_activation,
                'callbackRate': callback_rate_str,
                'triggerPriceType': 'market_price',
                'productType': 'USDT-FUTURES',
                'reduceOnly': True
            }

            # --- KORREKTUR (Fehler 40774 / tradeSide) ---
            if 'posSide' not in order_params:
                order_params['posSide'] = 'net'
            order_params['tradeSide'] = 'close'
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
        Führt den robusten 3-Schritt-Prozess zur Trade-Eröffnung aus.
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
            # posSide: 'net' und tradeSide: 'close' werden von den place_... Funktionen hinzugefügt
        }

        # 3. Stop-Loss (Trigger-Order ODER TSL)
        # --- START KORREKTUR: TSL-Logik DEAKTIVIERT, fällt IMMER auf fixen SL zurück ---
        try:
            # if tsl_config and tsl_config.get('enabled', False):
            #     # --- A) TRAILING STOP WIRD VERWENDET (DEAKTIVIERT) ---
            #     # Wir lassen die TSL-Logik hier aus, da sie API-Probleme verursacht.
            #     # Es wird IMMER der fixe SL verwendet, auch wenn TSL in config.toml auf true ist.
            #     logger.warning(f"[{symbol}] TSL ist konfiguriert, aber aufgrund von API-Problemen wird der FIXE SL verwendet.")
            #     # Fallthrough zu B)

            # # --- B) FIXER STOP-LOSS WIRD VERWENDET ---
            logger.info(f"[{symbol}] Schritt 2/3: Platziere fixen Stop-Loss ({close_side}) bei {sl_price} für Menge {final_amount}...")
            self.place_trigger_market_order(symbol, close_side, final_amount, sl_price, params=trigger_params)
            sl_success = True
            logger.info(f"[{symbol}] Schritt 2/3: ✅ Fixen Stop-Loss platziert.")

        except Exception as e_sl:
            logger.error(f"[{symbol}] ❌ KRITISCH: SL-Order fehlgeschlagen: {e_sl}. Position ist UNGESCHÜTZT!")
        # --- ENDE KORREKTUR ---

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
