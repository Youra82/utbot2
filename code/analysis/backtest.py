# code/analysis/backtest.py
import os
import sys
import json
import pandas as pd
import argparse

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.bitget_futures import BitgetFutures
from utilities.strategy_logic import calculate_signals, get_lower_timeframe

# (run_backtest Funktion bleibt gleich)
def run_backtest(data, params, initial_capital=1000, verbose=True):
    #... (CODE IST IDENTISCH ZUR LETZTEN FUNKTIONIERENDEN VERSION)
    risk_per_trade_percent = params.get('risk_per_trade_percent', 5.0)
    sl_multiplier = params.get('stop_loss_atr_multiplier', 1.5)
    trailing_stop_percent = params.get('trailing_tp_percent', 1.0)
    in_position = False
    position_side = None
    entry_price = 0.0
    trailing_stop_price = 0.0
    peak_price = 0.0
    position_size_coins = 0.0
    trades_count = 0
    wins_count = 0
    starting_capital = float(initial_capital)
    account_balance = float(initial_capital)
    trade_history = []
    fee_pct = 0.05 / 100
    for i in range(1, len(data)):
        if account_balance <= 0:
            if verbose: print("Konto liquidiert, Backtest wird beendet.")
            break
        prev_candle = data.iloc[i-1]
        current_candle = data.iloc[i]
        leverage = int(current_candle['leverage'])
        if in_position:
            exit_price, exit_reason = 0.0, ""
            if position_side == 'long':
                peak_price = max(peak_price, current_candle['high'])
                potential_new_stop = peak_price * (1 - trailing_stop_percent / 100)
                trailing_stop_price = max(trailing_stop_price, potential_new_stop)
                if current_candle['low'] <= trailing_stop_price: exit_price, exit_reason = trailing_stop_price, "TRAIL-STOP"
            elif position_side == 'short':
                peak_price = min(peak_price, current_candle['low'])
                potential_new_stop = peak_price * (1 + trailing_stop_percent / 100)
                trailing_stop_price = min(trailing_stop_price, potential_new_stop)
                if current_candle['high'] >= trailing_stop_price: exit_price, exit_reason = trailing_stop_price, "TRAIL-STOP"
            if exit_price == 0 and ((position_side == 'long' and prev_candle['sell_signal']) or (position_side == 'short' and prev_candle['buy_signal'])):
                exit_price, exit_reason = current_candle['open'], "GEGENSIGNAL"
            if exit_price > 0:
                price_diff = (exit_price - entry_price) if position_side == 'long' else (entry_price - exit_price)
                gross_pnl_usdt = price_diff * position_size_coins
                fees = (entry_price * position_size_coins + exit_price * position_size_coins) * fee_pct
                net_pnl_usdt = gross_pnl_usdt - fees
                account_balance += net_pnl_usdt
                if net_pnl_usdt > 0: wins_count += 1
                trades_count += 1
                trade_history.append({'exit_time': current_candle.name.strftime('%Y-%m-%d %H:%M'), 'side': position_side, 'pnl_usdt': net_pnl_usdt, 'account_balance': account_balance, 'leverage_used': leverage, 'exit_reason': exit_reason})
                in_position = False
        if not in_position and account_balance > 0:
            side_candidate = None
            if prev_candle['buy_signal']: side_candidate = 'long'
            elif prev_candle['sell_signal']: side_candidate = 'short'
            if side_candidate:
                entry_price = current_candle['open']
                atr_for_sl = prev_candle['atr']
                if side_candidate == 'long': initial_sl_price = entry_price - (atr_for_sl * sl_multiplier)
                else: initial_sl_price = entry_price + (atr_for_sl * sl_multiplier)
                distance_to_sl = abs(entry_price - initial_sl_price)
                if distance_to_sl == 0: continue
                risk_amount_usdt = account_balance * (risk_per_trade_percent / 100)
                position_size_coins = risk_amount_usdt / distance_to_sl
                required_margin = (position_size_coins * entry_price) / leverage
                if required_margin > account_balance: position_size_coins = (account_balance * 0.99) * leverage / entry_price
                if position_size_coins <= 0: continue
                in_position, position_side, peak_price, trailing_stop_price = True, side_candidate, entry_price, initial_sl_price
    win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
    final_pnl_usdt = account_balance - starting_capital
    total_pnl_pct = (final_pnl_usdt / starting_capital) * 100 if starting_capital > 0 else 0
    return {"total_pnl_pct": total_pnl_pct, "total_pnl_usdt": final_pnl_usdt, "trades_count": trades_count, "win_rate": win_rate, "params": params, "trade_history": trade_history, "critical_leverage": 0}

def load_data_for_backtest(symbol, timeframe, start_date_str, end_date_str, hide_messages=False):
    cache_dir = os.path.join(os.path.dirname(__file__), 'historical_data')
    os.makedirs(cache_dir, exist_ok=True)
    symbol_filename = symbol.replace('/', '-').replace(':', '-')
    cache_file = os.path.join(cache_dir, f"{symbol_filename}_{timeframe}.csv")
    data = None
    if os.path.exists(cache_file):
        if not hide_messages: print(f"Lade Daten aus lokaler Cache-Datei: {cache_file}")
        data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        data.index = pd.to_datetime(data.index, utc=True)
    download_start_date = start_date_str
    if data is not None and not data.empty:
        last_cached_date = data.index[-1].strftime('%Y-%m-%d')
        if not hide_messages: print(f"Letztes Datum im Cache: {last_cached_date}")
        if pd.to_datetime(last_cached_date, utc=True) < pd.to_datetime(end_date_str, utc=True):
            interval_minutes = 0
            if 'm' in timeframe: interval_minutes = int(timeframe.replace('m', ''))
            elif 'h' in timeframe: interval_minutes = int(timeframe.replace('h', '')) * 60
            download_start_date = (data.index[-1] + pd.Timedelta(minutes=interval_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            if not hide_messages: print("Cache ist aktuell. Keine neuen Daten zum Herunterladen.")
            download_start_date = None
    if download_start_date:
        if not hide_messages: print(f"Lade neue Daten von {download_start_date} bis {end_date_str} für {symbol}...")
        try:
            key_path = '/home/ubuntu/utbot2/secret.json'
            with open(key_path, "r") as f: api_setup = json.load(f)['envelope']
            bitget = BitgetFutures(api_setup)
            new_data = bitget.fetch_historical_ohlcv(symbol, timeframe, download_start_date, end_date_str)
            if new_data is not None and not new_data.empty:
                data = pd.concat([data, new_data]) if data is not None else new_data
                data = data[~data.index.duplicated(keep='first')]
                data.sort_index(inplace=True)
                data.to_csv(cache_file)
                if not hide_messages: print("Cache-Datei wurde aktualisiert.")
            else:
                if not hide_messages: print("Keine neuen Daten erhalten.")
        except Exception as e:
            if not hide_messages: print(f"\nEin Fehler beim Herunterladen der Daten ist aufgetreten: {e}")
            return None
    if data is not None and not data.empty:
        return data.loc[start_date_str:end_date_str]
    return None

if __name__ == "__main__": pass
