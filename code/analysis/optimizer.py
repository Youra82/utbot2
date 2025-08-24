# code/analysis/optimizer.py
import os
import sys
import json
import pandas as pd
import argparse
import time
from itertools import product

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.strategy_logic import calculate_signals
from analysis.backtest import run_backtest, load_data_for_backtest

def run_single_optimization_pass(param_combinations, base_params, initial_capital, data_cache):
    all_results = []
    total_runs_in_pass = sum(len(param_combinations) for tf in data_cache if data_cache[tf] is not None and not data_cache[tf].empty)
    current_run = 0
    print(f" -> Führe {total_runs_in_pass} Kombinationen in diesem Durchlauf durch...")
    for timeframe, data in data_cache.items():
        if data is None or data.empty: continue
        for params_to_test in param_combinations:
            current_run += 1
            print(f"\rTeste Kombination {current_run}/{total_runs_in_pass}...", end="")
            current_params = base_params.copy()
            current_params.update(params_to_test)
            current_params['timeframe'] = timeframe
            data_with_signals = calculate_signals(data.copy(), current_params)
            result = run_backtest(data_with_signals, current_params, initial_capital=initial_capital, verbose=False)
            all_results.append(result)
    return pd.DataFrame(all_results)

def get_best_safe_results(results_df):
    if results_df.empty: return None
    
    # Konvertiere die 'params' Spalte in separate Spalten
    params_df = pd.json_normalize(results_df['params'])
    
    # Kombiniere die Originaldaten (ohne 'params') mit den neuen Spalten
    results_with_flat_params = pd.concat([
        results_df.drop(columns=['params']).reset_index(drop=True),
        params_df.reset_index(drop=True)
    ], axis=1)

    # Filtere nach profitablen Ergebnissen
    safe_results = results_with_flat_params[results_with_flat_params['total_pnl_pct'] > 0].copy()

    if safe_results.empty: return None

    # Berechne eine Sicherheitsmarge für die Sortierung (nur bei dynamischem Hebel relevant)
    if 'base_leverage' in safe_results.columns:
        # Diese Logik für 'critical_leverage' ist für das Positionsgrößen-Modell nicht mehr primär
        safe_results['leverage_safety_margin'] = 1 
    
    return safe_results.sort_values(by=['total_pnl_pct', 'win_rate'], ascending=[False, False])

def run_optimization(start_date, end_date, timeframes_str, symbols_list, risk_percent=None, initial_capital=1000, top_n=10):
    print("Lade Basis-Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    with open(config_path, 'r') as f:
        default_params = json.load(f)

    if not symbols_list: symbols_to_optimize = [default_params['symbol']]
    else: symbols_to_optimize = symbols_list
    
    all_symbols_results_list = []
    
    for symbol_arg in symbols_to_optimize:
        base_params = default_params.copy()
        raw_symbol = symbol_arg
        if '/' not in raw_symbol: formatted_symbol = f"{raw_symbol.upper()}/USDT:USDT"
        else: formatted_symbol = raw_symbol.upper()
        base_params['symbol'] = formatted_symbol
        
        print(f"\n\n#################### START OPTIMIERUNG FÜR: {base_params['symbol']} ####################")
        timeframes_to_test = timeframes_str.split()
        
        param_grid = {
            'ut_atr_period': [7, 10, 14], 'ut_key_value': [1.0, 1.5],
            'stop_loss_atr_multiplier': [1.0, 1.5, 2.0],
            'trailing_tp_percent': [1.0, 1.5, 2.0],
            'base_leverage': [5, 10, 15]
        }
        base_params['use_dynamic_leverage'] = True
        
        if risk_percent is None:
            param_grid['risk_per_trade_percent'] = [2, 3, 5]
            print("INFO: Risiko pro Trade wird optimiert.")
        else:
            base_params['risk_per_trade_percent'] = risk_percent
            print(f"INFO: Festes Risiko pro Trade: {risk_percent:.1f}%")

        keys, values = zip(*param_grid.items())
        param_combinations = [dict(zip(keys, v)) for v in product(*values)]
        
        for combo in param_combinations:
            combo['min_leverage'] = combo['base_leverage'] * 0.5
            combo['max_leverage'] = combo['base_leverage'] * 1.5

        total_runs = len(param_combinations) * len(timeframes_to_test)
        print(f"\nStarte Optimierungslauf mit insgesamt {total_runs} Kombinationen...")
        
        data_cache = {tf: load_data_for_backtest(base_params['symbol'], tf, start_date, end_date) for tf in timeframes_to_test}
        results_df = run_single_optimization_pass(param_combinations, base_params, initial_capital, data_cache)
        
        print("\n\n--- Optimierung abgeschlossen ---")
        sorted_results = get_best_safe_results(results_df)

        if sorted_results is None:
            print(f"\n\033[0;31mWARNUNG: Für {base_params['symbol']} wurden keine profitablen Kombinationen gefunden.\033[0m")
            continue

        all_symbols_results_list.append(sorted_results)
        top_results = sorted_results.head(top_n)
        print(f"\nBeste PROFITABLE & SICHERE Ergebnisse für {base_params['symbol']} (Top {top_n}):")
        
        for i, row in top_results.reset_index(drop=True).iterrows():
            platz = i + 1
            print("\n" + "="*60)
            print(f"                  --- PLATZ {platz} ---")
            print("="*60)
            print("\n  LEISTUNG:")
            print(f"    Gewinn (PnL %):     {row['total_pnl_pct']:.2f} %")
            print(f"    Gewinn (PnL USDT):  {row['total_pnl_usdt']:.2f} USDT (Start: {initial_capital:.2f})")
            print(f"    Trefferquote:       {row['win_rate']:.2f} %")
            print(f"    Anzahl Trades:      {int(row['trades_count'])}")
            
            print("\n  GEFUNDENE OPTIMALE PARAMETER:")
            print(f"    Risiko pro Trade:   {row['risk_per_trade_percent']}%")
            print(f"    Hebel-Spanne:       {row['min_leverage']:.1f}x (Min) / {row['base_leverage']:.1f}x (Base) / {row['max_leverage']:.1f}x (Max)")
            print(f"    SL Multiplikator:   {row['stop_loss_atr_multiplier']}")
            print(f"    Trailing TP:        {row['trailing_tp_percent']:.2f}%")
            print(f"    Timeframe:          {row['timeframe']}")
            print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
            print(f"    UT Key Value:       {row['ut_key_value']:.1f}")
        print(f"\n#################### ENDE BERICHT FÜR: {base_params['symbol']} ####################\n")

    if len(all_symbols_results_list) > 1:
        print("\n" + "="*80)
        print("#################### FINALE GESAMTAUSWERTUNG (TOP 10 ÜBER ALLE SYMBOLE) ####################")
        print("="*80)

        master_df = pd.concat(all_symbols_results_list)
        final_sorted = get_best_safe_results(master_df)
        
        if final_sorted is not None:
            final_top_10 = final_sorted.head(10)
            print("\nDie absolut besten 10 Konfigurationen über alle getesteten Handelspaare:")
            for i, row in final_top_10.reset_index(drop=True).iterrows():
                platz = i + 1
                print("\n" + "="*60)
                print(f"                  --- GESAMT-PLATZ {platz} ---")
                print("="*60)
                print("\n  LEISTUNG:")
                print(f"    Gewinn (PnL %):     {row['total_pnl_pct']:.2f} %")
                print(f"    Gewinn (PnL USDT):  {row['total_pnl_usdt']:.2f} USDT (Start: {initial_capital:.2f})")
                
                print("\n  GEFUNDENE OPTIMALE PARAMETER:")
                print(f"    Handelspaar:        {row['symbol']}")
                print(f"    Risiko pro Trade:   {row['risk_per_trade_percent']}%")
                print(f"    Hebel-Spanne:       {row['min_leverage']:.1f}x (Min) / {row['base_leverage']:.1f}x (Base) / {row['max_leverage']:.1f}x (Max)")
                print(f"    SL Multiplikator:   {row['stop_loss_atr_multiplier']}")
                print(f"    Trailing TP:        {row['trailing_tp_percent']:.2f}%")
                print(f"    Timeframe:          {row['timeframe']}")
                print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
                print(f"    UT Key Value:       {row['ut_key_value']:.1f}")
        else:
            print("\nKeine profitablen Ergebnisse für eine finale Auswertung gefunden.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer mit Positionsgrößen-Management.")
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--timeframes', required=True)
    parser.add_argument('--symbols', nargs='+')
    parser.add_argument('--risk', type=float, dest='risk_percent', help="Festes Risiko pro Trade in %%. Weglassen, um zu optimieren.")
    parser.add_argument('--initial_capital', type=float, default=1000)
    parser.add_argument('--top', type=int, default=10, help="Anzahl der Top-Ergebnisse pro Symbol.")
    args = parser.parse_args()
    
    run_optimization(args.start, args.end, args.timeframes, args.symbols, args.risk_percent, initial_capital=args.initial_capital, top_n=args.top)
