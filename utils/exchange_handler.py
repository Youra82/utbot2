import ccxt
import time
import math
import logging

class ExchangeHandler:
    def __init__(self, config: dict):
        self.config = config
        self.session = ccxt.bitget({
            'apiKey': config['apiKey'],
            'secret': config['secret'],
            'password': config['password'],
            'enableRateLimit': True,
        })
        self.logger = logging.getLogger('ExchangeHandler')

    def fetch_open_positions(self, symbol: str):
        """Holt alle offenen Positionen für ein Symbol."""
        try:
            positions = self.session.fetch_positions([symbol])
            return [p for p in positions if float(p.get('contracts', 0)) != 0]
        except Exception as e:
            self.logger.error(f"[{symbol}] Fehler beim Abrufen der Positionen: {e}")
            return []

    def cleanup_all_open_orders(self, symbol: str):
        """Löscht alle offenen Orders für ein Symbol."""
        try:
            self.session.cancel_all_orders(symbol)
        except Exception as e:
            self.logger.warning(f"[{symbol}] Fehler beim Aufräumen der Orders: {e}")

    def create_market_order(self, symbol: str, side: str, amount: float, price: float = None, params: dict = None):
        """
        Erstellt eine Market-Order.
        Optional kann 'price' für Trigger-Orders angegeben werden.
        'params' kann zusätzliche ccxt-Parameter enthalten.
        """
        if params is None:
            params = {}

        try:
            rounded_amount = round(amount, 8)  # Robuste Rundung
            if price is not None:
                # Trigger/Conditional Market-Order
                rounded_price = round(price, 8)
                order_params = {**params, 'triggerPrice': rounded_price, 'reduceOnly': params.get('reduceOnly', False)}
                order = self.session.create_order(symbol, 'market', side, rounded_amount, None, order_params)
            else:
                # Standard Market-Order
                order = self.session.create_order(symbol, 'market', side, rounded_amount, None, params)

            self.logger.info(f"[{symbol}] Market-Order erfolgreich: {order}")
            return order

        except ccxt.ExchangeError as e:
            msg = str(e)
            self.logger.error(f"[{symbol}] Exchange-Fehler bei Market-Order: {msg}")

            # Spezifische Fehler abfangen
            if '22002' in msg or 'No position to close' in msg:
                # Position war bereits geschlossen
                self.logger.info(f"[{symbol}] Position war bereits geschlossen.")
                return None
            elif '40774' in msg:
                # Unilateral-Position Problem
                self.logger.warning(f"[{symbol}] Unilateral position – versuche reduceOnly anzupassen.")
                params['reduceOnly'] = True
                return self.create_market_order(symbol, side, amount, price, params)
            else:
                raise

    def close_position(self, symbol: str, position: dict):
        """
        Schließt eine Position robust.
        Prüft, ob Position existiert und wählt die richtige Seite.
        """
        pos_amount = float(position.get('contracts', 0))
        if abs(pos_amount) < 1e-9:
            self.logger.info(f"[{symbol}] Keine offene Position vorhanden.")
            return None

        close_side = 'sell' if position['side'] == 'long' else 'buy'
        try:
            return self.create_market_order(symbol, close_side, pos_amount, params={'reduceOnly': True})
        except Exception as e:
            self.logger.error(f"[{symbol}] Konnte Position nicht schließen: {e}")
            return None
