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

# --- STRATEGIE-LOGIK (aus run.py kopiert) ---
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

# --- BACKTESTING-ENGINE ---
def run_backtest(data, params):
    print("\n führe Backtest aus...")
    
    in_position = False
    position_side = None
    entry_price = 0.0
    total_pnl = 0.0
    trades_count = 0
    wins_count = 0
    
    # Gebühr pro Trade (Kauf/Verkauf) in Prozent
    fee_pct = 0.05 / 100 

    for i in range(1, len(data)):
        # Signale werden auf der Basis der *vorherigen* Kerze ausgelöst
        prev_candle = data.iloc[i-1]
        current_price = data.iloc[i]['open'] # Trade wird zum Eröffnungspreis der nächsten Kerze simuliert

        # Logik zum SCHLIESSEN von Positionen
        if in_position:
            if position_side == 'long' and prev_candle['sell_signal']:
                # Long-Position schließen
                pnl = (current_price - entry_price) / entry_price
                pnl -= 2 * fee_pct # Gebühr für Eröffnung und Schließung
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | CLOSE LONG  | PnL: {pnl*100:.2f}%")
                in_position = False
                position_side = None

            elif position_side == 'short' and prev_candle['buy_signal']:
                # Short-Position schließen
                pnl = (entry_price - current_price) / entry_price
                pnl -= 2 * fee_pct # Gebühr für Eröffnung und Schließung
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                print(f"{data.index[i].strftime('%Y-%m-%d %H:%M')} | CLOSE SHORT | PnL: {pnl*100:.2f}%")
                in_position = False
                position_side = None

        # Logik zum ERÖFFNEN von Positionen (Flip-Logik)
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

    # --- ERGEBNISSE ---
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
    print("Lade Konfiguration und verbinde mit der API...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    key_path = '/home/ubuntu/utbot2/secret.json' # Passe den Pfad bei Bedarf an
    
    with open(config_path, 'r') as f:
        params = json.load(f)
        params['timeframe'] = args.timeframe # Überschreibe Timeframe aus der config

    with open(key_path, "r") as f:
        api_setup = json.load(f)['envelope']
    
    bitget = BitgetFutures(api_setup)

    # --- DATEN HERUNTERLADEN ---
    print(f"Lade historische Daten für {params['symbol']} von {args.start} bis {args.end}...")
    try:
        data = bitget.fetch_historical_ohlcv(params['symbol'], args.timeframe, args.start, args.end)
        
        # --- STRATEGIE ANWENDEN & BACKTEST STARTEN ---
        data_with_signals = calculate_ut_signals(data, params)
        run_backtest(data_with_signals, params)

    except Exception as e:
        print(f"\nEin Fehler ist aufgetreten: {e}")
