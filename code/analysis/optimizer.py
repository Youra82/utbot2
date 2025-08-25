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

def run_single_optimization_pass(param_combinations, base_params, initial_capital, data_cache, start_date, end_date):
    """Führt einen einzelnen Optimierungsdurchlauf für eine gegebene Parameterliste durch."""
    all_results = []
    total_runs = sum(len(param_combinations) for tf in data_cache if data_cache[tf] is not None and not data_cache[tf].empty)
    current_run = 0

    print(f" -> Führe {total_runs} Kombinationen in diesem Durchlauf durch...")

    for timeframe, data in data_cache.items():
        if data is None or data.empty:
            continue

        for params_to_test in param_combinations:
            current_run += 1
            print(f"\rTeste Kombination {current_run}/{total_runs}...", end="")

            current_params = base_params.copy()
            current_params.update(params_to_test)
            current_params['timeframe'] = timeframe
            
            if 'leverage' in params_to_test:
                current_params['leverage'] = params_to_test['leverage']

            data_with_signals = calculate_signals(data.copy(), current_params)
            result = run_backtest(data_with_signals, current_params, initial_capital=initial_capital, verbose=False)
            all_results.append(result)
    
    return pd.DataFrame(all_results)

def get_best_safe_results(results_df):
    """Filtert und sortiert die Ergebnisse, um die beste sichere Konfiguration zu finden."""
    if results_df.empty:
        return None

    trade_histories = results_df['trade_history']
    params_col = results_df['params']
    results_df_no_history = results_df.drop('trade_history', axis=1)

    params_df = pd.json_normalize(results_df_no_history['params'])
    results_df_no_history = pd.concat([results_df_no_history.drop('params', axis=1), params_df], axis=1)
    
    results_df_final = pd.concat([results_df_no_history, params_col, trade_histories], axis=1)

    safe_results = results_df_final[
        (results_df_final['total_pnl_pct'] > 0) &
        (results_df_final['leverage'] < results_df_final['critical_leverage'])
    ].copy()

    if safe_results.empty:
        return None
    
    return safe_results.sort_values(
        by=['total_pnl_pct', 'critical_leverage', 'win_rate'], 
        ascending=[False, False, False]
    )

def run_optimization(start_date, end_date, timeframes_str, symbols_list, leverage=None, sl_multiplier=None, initial_capital=1000, top_n=10, fast_mode=False):
    print("Lade Basis-Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    with open(config_path, 'r') as f:
        default_params = json.load(f)

    if not symbols_list:
        symbols_to_optimize = [default_params['symbol']]
    else:
        symbols_to_optimize = symbols_list

    overall_best_results = []
    
    for symbol_arg in symbols_to_optimize:
        base_params = default_params.copy()
        raw_symbol = symbol_arg
        if '/' not in raw_symbol:
            formatted_symbol = f"{raw_symbol.upper()}/USDT:USDT"
            base_params['symbol'] = formatted_symbol
        else:
            base_params['symbol'] = raw_symbol.upper()
        
        print(f"\n\n#################### START OPTIMIERUNG FÜR: {base_params['symbol']} ####################")
        
        timeframes_to_test = timeframes_str.split()
        data_cache = {tf: load_data_for_backtest(base_params['symbol'], tf, start_date, end_date) for tf in timeframes_to_test}
        
        if fast_mode:
            print("\n--- STUFE 1: Grobe Suche (Benchmark) ---")
            param_grid = {
                'ut_atr_period': [7, 14], 'ut_key_value': [1.0, 2.0],
                'leverage': [10, 25], 'stop_loss_atr_multiplier': [1.0, 2.0]
            }
        else:
            param_grid = {
                'ut_atr_period': [7, 10, 14], 'ut_key_value': [1.0, 1.5, 2.0],
                'leverage': [5, 10, 15, 20, 25, 30, 35],
                'stop_loss_atr_multiplier': [1.0, 1.5, 2.0, 2.5]
            }

        keys, values = zip(*param_grid.items())
        param_combinations = [dict(zip(keys, v)) for v in product(*values)]
        
        results_df = run_single_optimization_pass(param_combinations, base_params, initial_capital, data_cache, start_date, end_date)
        
        best_coarse_result = get_best_safe_results(results_df)

        if best_coarse_result is None:
            print("\n\033[0;31mWARNUNG: Keine profitable Konfiguration gefunden.\033[0m")
            continue
            
        if fast_mode:
            print("\n--- STUFE 2: Feinsuche um die besten Werte ---")
            best_params = best_coarse_result.iloc[0]
            fine_param_grid = {
                'leverage': [max(5, best_params['leverage'] - 5), best_params['leverage'], best_params['leverage'] + 5],
                'stop_loss_atr_multiplier': [max(0.5, best_params['stop_loss_atr_multiplier'] - 0.5), best_params['stop_loss_atr_multiplier'], best_params['stop_loss_atr_multiplier'] + 0.5],
                'ut_atr_period': [max(1, best_params['ut_atr_period'] - 3), best_params['ut_atr_period'], best_params['ut_atr_period'] + 3],
                'ut_key_value': [max(0.5, best_params['ut_key_value'] - 0.5), best_params['ut_key_value'], best_params['ut_key_value'] + 0.5]
            }
            keys, values = zip(*fine_param_grid.items())
            fine_combinations = [dict(zip(keys, v)) for v in product(*values)]
            
            fine_results_df = run_single_optimization_pass(fine_combinations, base_params, initial_capital, {best_params['timeframe']: data_cache[best_params['timeframe']]}, start_date, end_date)
            final_results_df = pd.concat([results_df, fine_results_df]).drop_duplicates()
        else:
            final_results_df = results_df

        sorted_results = get_best_safe_results(final_results_df)
        
        if sorted_results is not None and not sorted_results.empty:
            overall_best_results.append(sorted_results.iloc[0].to_dict())
            top_results = sorted_results.head(top_n)
            print(f"\nBeste PROFITABLE & SICHERE Ergebnisse für {base_params['symbol']} (Top {top_n}):")
            for i, row in top_results.reset_index(drop=True).iterrows():
                # ... [rest of the printing logic remains the same]
                platz = i + 1
                print("\n" + "="*60)
                print(f"                  --- PLATZ {platz} ---")
                print("="*60)
                print("\n  LEISTUNG:")
                print(f"    Gewinn (PnL %):     {row['total_pnl_pct']:.2f} %")
                print(f"    Gewinn (PnL USDT):  {row['total_pnl_usdt']:.2f} USDT (Start: {initial_capital:.2f})")
                print("\n  GEFUNDENE OPTIMALE PARAMETER:")
                print(f"    Handelspaar:        {row['symbol']}")
                print(f"    Risiko pro Trade:   {row['risk_per_trade_percent']}%")
                print(f"    Hebel-Spanne:       {row['min_leverage']:.1f}x (Min) / {row['base_leverage']:.1f}x (Base) / {row['max_leverage']:.1f}x (Max)")
                print(f"    SL Multiplikator:   {row['stop_loss_atr_multiplier']}")
                print(f"    Trailing Stop:      {row['trailing_tp_percent']:.2f}%")
                print(f"    Timeframe:          {row['timeframe']}")
                print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
                print(f"    UT Key Value:       {row['ut_key_value']:.1f}")

    if len(overall_best_results) > 1:
        print("\n" + "="*80)
        print("#################### FINALE GESAMTAUSWERTUNG (TOP 10 ÜBER ALLE SYMBOLE) ####################")
        print("="*80)
        
        summary_df = pd.DataFrame(overall_best_results)
        final_ranking = summary_df.sort_values(by='total_pnl_pct', ascending=False).head(10)
        
        print("\nDie absolut besten 10 Konfigurationen über alle getesteten Handelspaare:")
        for i, row in final_ranking.reset_index(drop=True).iterrows():
            # ... [rest of the final summary printing logic]
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
            print(f"    Trailing Stop:      {row['trailing_tp_percent']:.2f}%")
            print(f"    Timeframe:          {row['timeframe']}")
            print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
            print(f"    UT Key Value:       {row['ut_key_value']:.1f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer mit Positionsgrößen-Management.")
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--timeframes', required=True)
    parser.add_argument('--symbols', nargs='+')
    parser.add_argument('--risk', type=float, dest='risk_percent', help="Festes Risiko pro Trade in %%. Weglassen, um zu optimieren.")
    parser.add_argument('--initial_capital', type=float, default=1000)
    parser.add_argument('--top', type=int, default=10, help="Anzahl der Top-Ergebnisse pro Symbol.")
    parser.add_argument('--fast', action='store_true', help="Aktiviert den schnellen 2-Stufen-Optimierungsmodus.")
    args = parser.parse_args()
    
    run_optimization(args.start, args.end, args.timeframes, args.symbols, args.risk_percent, initial_capital=args.initial_capital, top_n=args.top, fast_mode=args.fast)
