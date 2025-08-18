# code/analysis/backtest.py
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
import time
import argparse
from datetime import datetime

# Pfad für Modulimporte anpassen
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.bitget_futures import BitgetFutures

# --- STRATEGIE-LOGIK (unverändert) ---
def calculate_ut_signals(data, params):
    src = data['close']
    data['atr'] = ta.volatility.average_true_range(data['high'], data['low'], data['close'], window=params['ut_atr_period'])
    n_loss = params['ut_key_value'] * data['atr']
    x_atr_trailing_stop = np.zeros(len(data))
    for i in range(len(data)):
        if i == 0: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
        else:
            if src.iloc[i] > x_atr_trailing_stop[i-1] and src.iloc[i-1] > x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = max(x_atr_trailing_stop[i-1], src.iloc[i] - n_loss.iloc[i])
            elif src.iloc[i] < x_atr_trailing_stop[i-1] and src.iloc[i-1] < x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = min(x_atr_trailing_stop[i-1], src.iloc[i] + n_loss.iloc[i])
            else:
                if src.iloc[i] > x_atr_trailing_stop[i-1]: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
                else: x_atr_trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    data['buy_signal'] = (src > data['x_atr_trailing_stop']) & (src.shift(1) <= data['x_atr_trailing_stop'].shift(1))
    data['sell_signal'] = (src < data['x_atr_trailing_stop']) & (src.shift(1) >= data['x_atr_trailing_stop'].shift(1))
    return data

# --- BACKTESTING-ENGINE (unverändert) ---
def run_backtest(data, params):
    print("\n führe Backtest aus...")
    
    in_position = False
    position_side = None
    entry_price = 0.0
    total_pnl = 0.0
    trades_count = 0
    wins_count = 0
    
    fee_pct = 0.05 / 100 

    for i in range(1, len(data)):
        prev_candle = data.iloc[i-1]
        current_price = data.iloc[i]['open']

        if in_position:
            if position_side == 'long' and prev_candle['sell_signal']:
                pnl = ((current_price - entry_price) / entry_price) - (2 * fee_pct)
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | CLOSE LONG  | PnL: {pnl*100:.2f}%")
                in_position = False
                position_side = None
            elif position_side == 'short' and prev_candle['buy_signal']:
                pnl = ((entry_price - current_price) / entry_price) - (2 * fee_pct)
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | CLOSE SHORT | PnL: {pnl*100:.2f}%")
                in_position = False
                position_side = None

        if not in_position:
            if prev_candle['buy_signal'] and params['use_longs']:
                in_position = True
                position_side = 'long'
                entry_price = current_price
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | OPEN LONG   | @ {entry_price:.2f}")
            elif prev_candle['sell_signal'] and params['use_shorts']:
                in_position = True
                position_side = 'short'
                entry_price = current_price
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | OPEN SHORT  | @ {entry_price:.2f}")

    win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
    
    print("\n--- Backtest-Ergebnisse ---")
    print(f"Zeitraum: {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")
    print(f"Timeframe: {params['timeframe']}")
    print("-" * 27)
    print(f"Gesamt-PnL (ungehebelt): {total_pnl * 100:.2f}%")
    print(f"Anzahl Trades: {trades_count}")
    print(f"Gewonnene Trades: {wins_count}")
    print(f"Trefferquote: {win_rate:.2f}%")
    print("---------------------------")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Backtest für den Envelope Bot.")
    parser.add_argument('--start', required=True, help="Startdatum im Format YYYY-MM-DD")
    parser.add_argument('--end', required=True, help="Enddatum im Format YYYY-MM-DD")
    parser.add_argument('--timeframe', required=True, help="Timeframe (z.B. 15m, 1h, 4h, 1d)")
    
    args = parser.parse_args()

    # --- KONFIGURATION & API-VERBINDUNG ---
    print("Lade Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    key_path = '/home/ubuntu/utbot2/secret.json'
    
    with open(config_path, 'r') as f:
        params = json.load(f)
        params['timeframe'] = args.timeframe

    # --- NEU: DATEN-CACHE LOGIK ---
    cache_dir = os.path.join(os.path.dirname(__file__), 'historical_data')
    os.makedirs(cache_dir, exist_ok=True)
    symbol_filename = params['symbol'].replace('/', '-').replace(':', '-')
    cache_file = os.path.join(cache_dir, f"{symbol_filename}_{args.timeframe}.csv")

    data = None
    
    if os.path.exists(cache_file):
        print(f"Lade Daten aus lokaler Cache-Datei: {cache_file}")
        data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        # Sicherstellen, dass der Index ein DatetimeIndex ist
        data.index = pd.to_datetime(data.index, utc=True)

    # Prüfen, ob neue Daten heruntergeladen werden müssen
    download_start_date = args.start
    if data is not None and not data.empty:
        last_cached_date = data.index[-1].strftime('%Y-%m-%d')
        print(f"Letztes Datum im Cache: {last_cached_date}")
        if pd.to_datetime(last_cached_date) < pd.to_datetime(args.end):
             # Lade nur die Daten, die nach dem letzten Eintrag im Cache liegen
             download_start_date = (data.index[-1] + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            print("Cache ist aktuell. Keine neuen Daten zum Herunterladen.")
            download_start_date = None # Nichts herunterladen
    
    if download_start_date:
        print(f"Lade neue Daten von {download_start_date} bis {args.end}...")
        try:
            with open(key_path, "r") as f:
                api_setup = json.load(f)['envelope']
            bitget = BitgetFutures(api_setup)
            
            new_data = bitget.fetch_historical_ohlcv(params['symbol'], args.timeframe, download_start_date, args.end)
            
            if data is None:
                data = new_data
            else:
                data = pd.concat([data, new_data])

            # Duplikate entfernen und speichern
            data.drop_duplicates(inplace=True)
            data.sort_index(inplace=True)
            data.to_csv(cache_file)
            print("Cache-Datei wurde aktualisiert.")

        except Exception as e:
            print(f"\nEin Fehler beim Herunterladen der Daten ist aufgetreten: {e}")
            sys.exit(1)
    
    if data is not None and not data.empty:
        # Schneide den DataFrame auf den vom Benutzer angeforderten Bereich zu
        data_for_backtest = data[args.start:args.end]
        
        # --- STRATEGIE ANWENDEN & BACKTEST STARTEN ---
        data_with_signals = calculate_ut_signals(data_for_backtest, params)
        run_backtest(data_with_signals, params)
    else:
        print("Keine Daten für den Backtest verfügbar.")

