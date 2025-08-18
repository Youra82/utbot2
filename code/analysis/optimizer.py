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

def run_optimization(start_date, end_date, timeframe):
    """
    Führt eine Parameter-Optimierung durch und gibt die besten Ergebnisse aus.
    """
    print("Lade Basis-Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    with open(config_path, 'r') as f:
        base_params = json.load(f)
        base_params['timeframe'] = timeframe

    # 1. Lade die Basis-Daten einmalig
    data = load_data_for_backtest(base_params['symbol'], timeframe, start_date, end_date)
    if data is None or data.empty:
        print("Keine Daten für die Optimierung verfügbar. Breche ab.")
        return

    # 2. Definiere die zu testenden Parameter-Bereiche
    param_grid = {
        'ut_atr_period': [7, 10, 14],
        'ut_key_value': [1.0, 1.5, 2.0],
        'stop_loss_atr_multiplier': [1.5, 2.0, 2.5],
        'adx_threshold': [20, 25, 30]
    }
    
    keys, values = zip(*param_grid.items())
    param_combinations = [dict(zip(keys, v)) for v in product(*values)]
    
    all_results = []
    total_runs = len(param_combinations)
    print(f"\nStarte Optimierungslauf mit {total_runs} Kombinationen...")

    # 3. Schleife durch alle Kombinationen
    for i, params_to_test in enumerate(param_combinations):
        current_params = base_params.copy()
        current_params.update(params_to_test)
        
        print(f"\rTeste Kombination {i+1}/{total_runs}...", end="")

        data_with_signals = calculate_signals(data.copy(), current_params)
        result = run_backtest(data_with_signals, current_params, verbose=False)
        all_results.append(result)

    # 4. Ergebnisse auswerten und anzeigen
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

    # NEUE, ÜBERSICHTLICHE BLOCK-AUSGABE
    print("\nBeste Ergebnisse (Top 10):")
    
    # .reset_index() sorgt für eine saubere Platzierungs-Nummer von 1 bis 10
    for i, row in top_10_results.reset_index(drop=True).iterrows():
        platz = i + 1
        print("\n" + "="*25)
        print(f"    --- PLATZ {platz} ---")
        print("="*25)
        
        print("\n  LEISTUNG:")
        print(f"    Gewinn (PnL):     {row['total_pnl_pct']:.2f} %")
        print(f"    Trefferquote:     {row['win_rate']:.2f} %")
        print(f"    Anzahl Trades:    {int(row['trades_count'])}")
        
        print("\n  EINGESTELLTE PARAMETER:")
        print(f"    UT ATR Periode:   {int(row['ut_atr_period'])}")
        print(f"    UT Key Value:     {row['ut_key_value']:.1f}")
        print(f"    SL Multiplikator: {row['stop_loss_atr_multiplier']:.1f}")
        print(f"    ADX Schwellenwert:{int(row['adx_threshold'])}")
        
    print("\n" + "="*25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer für den Envelope Bot.")
    parser.add_argument('--start', required=True, help="Startdatum im Format YYY-MM-DD")
    parser.add_argument('--end', required=True, help="Enddatum im Format Y-MM-DD")
    parser.add_argument('--timeframe', required=True, help="Timeframe (z.B. 15m, 1h, 4h, 1d)")
    args = parser.parse_args()

    run_optimization(args.start, args.end, args.timeframe)
