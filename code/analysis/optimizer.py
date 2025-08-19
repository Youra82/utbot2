# code/analysis/optimizer.py
import os
import sys
import json
import pandas as pd
import argparse
from itertools import product

# Pfad anpassen, um Module aus dem Hauptprojekt zu importieren
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.strategy_logic import calculate_signals
from analysis.backtest import run_backtest, load_data_for_backtest

def run_optimization(start_date, end_date, timeframes_str, symbol=None):
    """
    Führt eine Parameter-Optimierung über mehrere Timeframes durch.
    """
    print("Lade Basis-Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    with open(config_path, 'r') as f:
        base_params = json.load(f)

    # Überschreibe das Symbol, wenn eines übergeben wurde
    if symbol:
        print(f"Info: Symbol '{base_params['symbol']}' aus der Konfiguration wird durch '{symbol}' überschrieben.")
        base_params['symbol'] = symbol

    # Erstelle eine Liste aus dem Timeframe-String
    timeframes_to_test = timeframes_str.split()
    
    # Definiere die zu testenden Parameter-Bereiche
    param_grid = {
        'ut_atr_period': [7, 10, 14],
        'ut_key_value': [1.0, 1.5, 2.0],
        'stop_loss_atr_multiplier': [1.5, 2.0, 2.5],
        'adx_threshold': [20, 25, 30],
        'adx_window': [14, 20, 25] 
    }
    
    keys, values = zip(*param_grid.items())
    param_combinations = [dict(zip(keys, v)) for v in product(*values)]
    
    all_results = []
    total_runs = len(param_combinations) * len(timeframes_to_test)
    current_run = 0
    
    print(f"\nStarte Optimierungslauf für {len(timeframes_to_test)} Timeframes mit insgesamt {total_runs} Kombinationen...")

    for timeframe in timeframes_to_test:
        print(f"\n--- Bearbeite Timeframe: {timeframe} ---")
        
        data = load_data_for_backtest(base_params['symbol'], timeframe, start_date, end_date)
        if data is None or data.empty:
            print(f"Keine Daten für Timeframe {timeframe} gefunden. Überspringe.")
            current_run += len(param_combinations)
            continue

        for params_to_test in param_combinations:
            current_run += 1
            print(f"\rTeste Kombination {current_run}/{total_runs}...", end="")

            # Sicherheits-Check für ausreichend Daten
            required_data_points = params_to_test.get('adx_window', 14) * 2
            if len(data) < required_data_points:
                continue

            current_params = base_params.copy()
            current_params.update(params_to_test)
            current_params['timeframe'] = timeframe

            data_with_signals = calculate_signals(data.copy(), current_params)
            result = run_backtest(data_with_signals, current_params, verbose=False)
            all_results.append(result)

    if not all_results:
        print("\n\nKeine Ergebnisse erzielt.")
        return
        
    print("\n\n--- Optimierung abgeschlossen ---")
    results_df = pd.DataFrame(all_results)
    
    params_df = pd.json_normalize(results_df['params'])
    results_df = pd.concat([results_df.drop('params', axis=1), params_df], axis=1)
    
    sorted_results = results_df.sort_values(
        by=['total_pnl_pct', 'win_rate', 'trades_count'], 
        ascending=[False, False, False]
    )

    top_10_results = sorted_results.head(10)

    print("\nBeste Ergebnisse (Top 10 über alle Timeframes):")
    
    for i, row in top_10_results.reset_index(drop=True).iterrows():
        platz = i + 1
        print("\n" + "="*30)
        print(f"     --- PLATZ {platz} ---")
        print("="*30)
        
        print("\n  LEISTUNG:")
        print(f"    Gewinn (PnL):       {row['total_pnl_pct']:.2f} %")
        print(f"    Trefferquote:       {row['win_rate']:.2f} %")
        print(f"    Anzahl Trades:    {int(row['trades_count'])}")
        
        print("\n  EINGESTELLTE PARAMETER:")
        print(f"    Timeframe:          {row['timeframe']}")
        print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
        print(f"    UT Key Value:       {row['ut_key_value']:.1f}")
        print(f"    SL Multiplikator:   {row['stop_loss_atr_multiplier']:.1f}")
        print(f"    ADX Schwellenwert:  {int(row['adx_threshold'])}")
        print(f"    ADX Window:         {int(row['adx_window'])}")
        
    print("\n" + "="*30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer für den Envelope Bot.")
    parser.add_argument('--start', required=True, help="Startdatum im Format YYYY-MM-DD")
    parser.add_argument('--end', required=True, help="Enddatum im Format YYYY-MM-DD")
    parser.add_argument('--timeframes', required=True, help="Eine Liste von Timeframes, getrennt durch Leerzeichen")
    parser.add_argument('--symbol', help="Optionales Handelspaar (z.B. BTC/USDT:USDT), überschreibt die config.json")
    args = parser.parse_args()

    run_optimization(args.start, args.end, args.timeframes, args.symbol)
