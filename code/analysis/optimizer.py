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
    
    # Erzeuge alle möglichen Kombinationen der Parameter
    keys, values = zip(*param_grid.items())
    param_combinations = [dict(zip(keys, v)) for v in product(*values)]
    
    all_results = []
    total_runs = len(param_combinations)
    print(f"\nStarte Optimierungslauf mit {total_runs} Kombinationen...")

    # 3. Schleife durch alle Kombinationen
    for i, params_to_test in enumerate(param_combinations):
        current_params = base_params.copy()
        current_params.update(params_to_test)
        
        print(f"[{i+1}/{total_runs}] Teste: {params_to_test}")

        data_with_signals = calculate_signals(data.copy(), current_params)
        result = run_backtest(data_with_signals, current_params, verbose=False) # verbose=False, um die Ausgabe sauber zu halten
        all_results.append(result)

    # 4. Ergebnisse auswerten und anzeigen
    if not all_results:
        print("Keine Ergebnisse erzielt.")
        return
        
    print("\n--- Optimierung abgeschlossen ---")
    results_df = pd.DataFrame(all_results)
    
    # Füge Parameter als Spalten hinzu für bessere Lesbarkeit
    params_df = pd.json_normalize(results_df['params'])
    results_df = pd.concat([results_df.drop('params', axis=1), params_df], axis=1)
    
    # Sortiere nach der besten Metrik, z.B. PnL
    sorted_results = results_df.sort_values(by="total_pnl_pct", ascending=False)

    print("\nBeste Ergebnisse (Top 10):")
    # Spalten für die Anzeige auswählen
    display_cols = [
        'total_pnl_pct', 'win_rate', 'trades_count', 
        'ut_atr_period', 'ut_key_value', 'stop_loss_atr_multiplier', 'adx_threshold'
    ]
    print(sorted_results[display_cols].head(10).to_string())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer für den Envelope Bot.")
    parser.add_argument('--start', required=True, help="Startdatum im Format YYYY-MM-DD")
    parser.add_argument('--end', required=True, help="Enddatum im Format YYYY-MM-DD")
    parser.add_argument('--timeframe', required=True, help="Timeframe (z.B. 15m, 1h, 4h, 1d)")
    args = parser.parse_args()

    run_optimization(args.start, args.end, args.timeframe)
