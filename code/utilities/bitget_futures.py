import ccxt
import time
import pandas as pd
from typing import Any, Optional, Dict, List

class BitgetFutures():
    def __init__(self, api_setup: Optional[Dict[str, Any]] = None) -> None:

        if api_setup == None:
            self.session = ccxt.bitget()
        else:
            api_setup.setdefault("options", {"defaultType": "future"})
            self.session = ccxt.bitget(api_setup)

        self.markets = self.session.load_markets()
    
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            return self.session.fetch_ticker(symbol)
        except Exception as e:
            raise Exception(f"Failed to fetch ticker for {symbol}: {e}")

    def fetch_min_amount_tradable(self, symbol: str) -> float:
        try:
            return self.markets[symbol]['limits']['amount']['min']
        except Exception as e:
            raise Exception(f"Failed to fetch minimum amount tradable: {e}")

    def fetch_min_cost(self, symbol: str) -> float:
        """
        Fetches the minimum cost (notional value) for a trade.
        """
        try:
            if not self.markets:
                self.markets = self.session.load_markets()
            
            market_info = self.markets.get(symbol)
            if market_info and 'limits' in market_info and 'cost' in market_info['limits'] and market_info['limits']['cost']['min'] is not None:
                return float(market_info['limits']['cost']['min'])
            else:
                print(f"Warnung: Minimalkosten für {symbol} nicht in den API-Daten gefunden. Verwende Fallback-Wert 5.0 USDT.")
                return 5.0
        except Exception as e:
            raise Exception(f"Failed to fetch minimum cost for {symbol}: {e}")

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        try:
            return self.session.amount_to_precision(symbol, amount)
        except Exception as e:
            raise Exception(f"Failed to convert amount {amount} {symbol} to precision", e)

    def price_to_precision(self, symbol: str, price: float) -> str:
        try:
            return self.session.price_to_precision(symbol, price)
        except Exception as e:
            raise Exception(f"Failed to convert price {price} to precision for {symbol}", e)

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if params is None:
            params = {}
        try:
            return self.session.fetch_balance(params)
        except Exception as e:
            raise Exception(f"Failed to fetch balance: {e}")

    def fetch_order(self, id: str, symbol: str) -> Dict[str, Any]:
        try:
            return self.session.fetch_order(id, symbol)
        except Exception as e:
            raise Exception(f"Failed to fetch order {id} info for {symbol}: {e}")

    def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            return self.session.fetch_open_orders(symbol)
        except Exception as e:
            raise Exception(f"Failed to fetch open orders: {e}")

    def fetch_open_trigger_orders(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            return self.session.fetch_open_orders(symbol, params={'stop': True})
        except Exception as e:
            raise Exception(f"Failed to fetch open trigger orders: {e}")

    def fetch_closed_trigger_orders(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            return self.session.fetch_closed_orders(symbol, params={'stop': True})
        except Exception as e:
            raise Exception(f"Failed to fetch closed trigger orders: {e}")

    def cancel_order(self, id: str, symbol: str) -> Dict[str, Any]:
        try:
            return self.session.cancel_order(id, symbol)
        except Exception as e:
            raise Exception(f"Failed to cancel the {symbol} order {id}", e)

    def cancel_trigger_order(self, id: str, symbol: str) -> Dict[str, Any]:
        try:
            return self.session.cancel_order(id, symbol, params={'stop': True})
        except Exception as e:
            raise Exception(f"Failed to cancel the {symbol} trigger order {id}", e)

    def fetch_open_positions(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            positions = self.session.fetch_positions([symbol])
            real_positions = []
            for position in positions:
                if position and position.get('contracts') is not None and float(position['contracts']) > 0:
                    real_positions.append(position)
            return real_positions
        except Exception as e:
            raise Exception(f"Failed to fetch open positions: {e}")

    def flash_close_position(self, symbol: str, side: Optional[str] = None) -> Dict[str, Any]:
        try:
            positions = self.fetch_open_positions(symbol)
            if not positions:
                raise Exception(f"No open position found for {symbol} to close.")
            
            position_info = positions[0]
            amount = float(position_info['contracts'])
            side_to_close = 'buy' if position_info['side'] == 'short' else 'sell'
            
            return self.place_market_order(symbol, side_to_close, amount, reduce=True)
            
        except Exception as e:
            raise Exception(f"Failed to flash close position for {symbol}: {e}")

    def set_margin_mode(self, symbol: str, margin_mode: str = 'isolated') -> None:
        """Sets the margin mode for a given symbol."""
        try:
            self.session.set_margin_mode(margin_mode, symbol)
        except ccxt.ExchangeError as e:
            # Catch a specific CCXT exception if it's already in the desired mode
            if "Margin mode already set" in str(e):
                print(f"Info: Margin mode for {symbol} is already set to {margin_mode}.")
            else:
                raise Exception(f"Failed to set margin mode: {e}")
        except Exception as e:
            raise Exception(f"Failed to set margin mode: {e}")

    def set_leverage(self, symbol: str, leverage: int, params: Optional[Dict[str, Any]] = None) -> None:
        """Sets the leverage for a given symbol."""
        try:
            self.session.set_leverage(leverage, symbol, params)
        except ccxt.ExchangeError as e:
            if "Leverage already set" in str(e) or "not need to be modified" in str(e):
                print(f"Info: Leverage for {symbol} is already set to {leverage}x.")
            else:
                raise Exception(f"Failed to set leverage: {e}")
        except Exception as e:
            raise Exception(f"Failed to set leverage: {e}")

    def fetch_recent_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        try:
            ohlcv_data = self.session.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            return df
        except Exception as e:
            raise Exception(f"Failed to fetch OHLCV data for {symbol} in timeframe {timeframe}: {e}")

    def place_market_order(self, symbol: str, side: str, amount: float, reduce: bool = False) -> Dict[str, Any]:
        try:
            params = {'reduceOnly': reduce}
            return self.session.create_order(symbol, 'market', side, amount, params=params)
        except Exception as e:
            raise Exception(f"Failed to place market order of {amount} {symbol}: {e}")

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float, reduce: bool = False) -> Dict[str, Any]:
        try:
            params = {'reduceOnly': reduce}
            return self.session.create_order(symbol, 'limit', side, amount, price, params=params)
        except Exception as e:
            raise Exception(f"Failed to place limit order of {amount} {symbol} at price {price}: {e}")

    def place_trigger_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, reduce: bool = False) -> Optional[Dict[str, Any]]:
        try:
            params = {
                'stopPrice': trigger_price,
                'reduceOnly': reduce,
            }
            return self.session.create_order(symbol, 'market', side, amount, params=params)
        except Exception as e:
            raise Exception(f"Failed to place trigger market order: {e}")

    def place_trigger_limit_order(self, symbol: str, side: str, amount: float, trigger_price: float, price: float, reduce: bool = False) -> Optional[Dict[str, Any]]:
        try:
            params = {
                'stopPrice': trigger_price,
                'reduceOnly': reduce,
            }
            return self.session.create_order(symbol, 'limit', side, amount, price, params=params)
        except Exception as e:
            raise Exception(f"Failed to place trigger limit order: {e}")
