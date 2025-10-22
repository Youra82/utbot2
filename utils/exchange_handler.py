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

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        try:
            try:
                self.session.set_margin_mode(margin_mode.lower(), symbol)
            except Exception as e:
                 if 'Margin mode is the same' not in str(e): 
                     logger.warning(f"Set margin mode failed: {e}")

            if margin_mode.lower() == 'isolated':
                self.session.set_leverage(leverage, symbol, params={'holdSide': 'long'})
                self.session.set_leverage(leverage, symbol, params={'holdSide': 'short'})
            else:
                self.session.set_leverage(leverage, symbol)
            logger.info(f"Hebel für {symbol} erfolgreich auf {leverage}x gesetzt.")
        except Exception as e:
            if 'repeat submit' in str(e) or 'Leverage not changed' in str(e):
                logger.info(f"Hebel für {symbol} ist bereits auf {leverage}x gesetzt.")
            else:
                logger.error(f"Fehler beim Setzen des Hebels: {e}"); raise

    # --- NEUE FUNKTION (Die fehlende Implementierung) ---
    def create_market_order_with_sl_tp(self, symbol: str, side: str, amount: float, sl_price: float, tp_price: float):
        """
        Führt den 3-Schritt-Prozess zur Trade-Eröffnung aus:
        1. Market-Order (Einstieg)
        2. Plan-Order (Stop-Loss)
        3. Plan-Order (Take-Profit)
        """
        logger.info(f"[{symbol}] 1/3: Platziere Market-Order ({side}, {amount})...")
        try:
            # 1. Market-Order (Einstieg)
            market_order = self.create_market_order(symbol, side, amount)
            logger.info(f"[{symbol}] 1/3: ✅ Market-Order platziert: {market_order['id']}")
        except Exception as e:
            logger.error(f"[{symbol}] ❌ FEHLER: Market-Order fehlgeschlagen: {e}")
            raise # Wenn der Einstieg fehlschlägt, den gesamten Trade abbrechen

        # 2. Definiere die Schließungs-Richtung
        close_side = 'sell' if side == 'buy' else 'buy'
        
        # 3. Stop-Loss (Plan-Order)
        try:
            logger.info(f"[{symbol}] 2/3: Platziere Stop-Loss ({close_side}) bei {sl_price}...")
            # Wir verwenden die bereits vorhandene Hilfsfunktion
            self.place_trigger_market_order(
                symbol, 
                close_side, 
                amount, 
                sl_price, 
                params={'planType': 'stop_loss'} # Bitget-spezifischer Param für SL
            )
            logger.info(f"[{symbol}] 2/3: ✅ Stop-Loss platziert.")
        except Exception as e:
            # WICHTIG: Loggen, aber nicht abbrechen, damit der TP noch gesetzt werden kann
            logger.error(f"[{symbol}] ❌ KRITISCH: SL-Order fehlgeschlagen: {e}. Position ist UNGESCHÜTZT!")

        # 4. Take-Profit (Plan-Order)
        try:
            logger.info(f"[{symbol}] 3/3: Platziere Take-Profit ({close_side}) bei {tp_price}...")
            self.place_trigger_market_order(
                symbol, 
                close_side, 
                amount, 
                tp_price, 
                params={'planType': 'take_profit'} # Bitget-spezifischer Param für TP
            )
            logger.info(f"[{symbol}] 3/3: ✅ Take-Profit platziert.")
        except Exception as e:
            logger.error(f"[{symbol}] ❌ WARNUNG: TP-Order fehlgeschlagen: {e}.")

        # 5. Gebe die ursprüngliche Market-Order zurück (wichtig für 'open_trades.json')
        return market_order
    # --- ENDE NEUE FUNKTION ---

    def create_market_order(self, symbol: str, side: str, amount: float):
        """Erstellt eine reine Market-Order. (Von JaegerBot)"""
        return self.session.create_order(symbol, 'market', side, amount)

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, params: dict = None):
        """Platziert eine SL- oder TP-Order als Trigger-Market-Order. (Von JaegerBot)"""
        order_params = {'stopPrice': self.session.price_to_precision(symbol, trigger_price), **(params or {})}
        return self.session.create_order(symbol, 'market', side, amount, None, order_params)

    # --- Standard-Hilfsfunktionen ---
    def fetch_usdt_balance(self):
        try:
            balance = self.session.fetch_balance()
            if 'USDT' in balance and 'free' in balance['USDT']:
                return float(balance['USDT']['free'])
            return 0.0
        except Exception as e: logger.error(f"Fehler beim Abrufen des Guthabens: {e}"); raise
        
    def fetch_ohlcv(self, symbol, timeframe, limit):
        try:
            ohlcv = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e: logger.error(f"Fehler beim Laden der Kerzendaten: {e}"); raise
        
    def fetch_open_positions(self, symbol: str):
        try:
            all_positions = self.session.fetch_positions([symbol])
            return [p for p in all_positions if p.get('contracts') is not None and float(p['contracts']) > 0]
        except Exception as e: logger.error(f"Fehler beim Abrufen offener Positionen: {e}"); raise
        
    def fetch_trade_history(self, symbol: str, since_timestamp: int):
        try:
            time.sleep(2)
            return self.session.fetch_my_trades(symbol, since=since_timestamp, limit=50)
        except Exception as e: logger.error(f"Fehler beim Abrufen der Trade-Historie: {e}"); raise
