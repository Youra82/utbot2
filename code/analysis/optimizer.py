# code/analysis/optimizer.py
import os
import sys
import json
import pandas as pd
import argparse
import time
from itertools import product

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.strategy_logic import calculate_signals, get_lower_timeframe
from analysis.backtest import run_backtest, load_data_for_backtest

def run_single_optimization_pass(param_combinations, base_params, initial_capital, data_cache, ltf_data_cache, start_date, end_date):
    all_results = []
    total_runs = sum(len(param_combinations) for tf in data_cache if data_cache[tf] is not None and not data_cache[tf].empty)
    current_run = 0
    print(f" -> Führe {total_runs} Kombinationen in diesem Durchlauf durch...")
    
    for timeframe, data in data_cache.items():
        if data is None or data.empty: continue
        
        lower_timeframe = get_lower_timeframe(timeframe)
        ltf_data = ltf_data_cache.get(lower_timeframe)
        
        for params_to_test in param_combinations:
            current_run += 1
            print(f"\rTeste Kombination {current_run}/{total_runs}...", end="")
            current_params = base_params.copy()
            current_params.update(params_to_test)
            current_params['timeframe'] = timeframe
            
            # Übergebe BEIDE Datensätze an die Strategie-Logik
            data_with_signals = calculate_signals(data.copy(), current_params, ltf_data=ltf_data.copy() if ltf_data is not None else None)
            result = run_backtest(data_with_signals, current_params, initial_capital=initial_capital)
            all_results.append(result)
            
    return pd.DataFrame(all_results)

# (get_best_safe_results bleibt gleich)
def get_best_safe_results(results_df):
    if results_df.empty: return None
    if 'params' in results_df.columns:
        params_df = pd.json_normalize(results_df['params'])
        results_with_flat_params = pd.concat([results_df.drop(columns=['params']).reset_index(drop=True), params_df.reset_index(drop=True)], axis=1)
    else:
        results_with_flat_params = results_df
    safe_results = results_with_flat_params[results_with_flat_params['total_pnl_pct'] > 0].copy()
    if safe_results.empty: return None
    return safe_results.sort_values(by=['total_pnl_pct', 'win_rate'], ascending=[False, False])

def run_optimization(start_date, end_date, timeframes_str, symbols_list, risk_percent=None, initial_capital=1000, top_n=10):
    # (Der Anfang bleibt gleich)
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
            'stop_loss_atr_multiplier': [1.0, 1.5],
            'trailing_tp_percent': [1.0, 1.5],
            'base_leverage': [5, 10, 15],
            'ltf_vol_sensitivity': [1.0, 1.5, 2.0]
        }
        base_params['use_dynamic_leverage'] = True
        
        if risk_percent is None:
            param_grid['risk_per_trade_percent'] = [3, 5]
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
        
        # Lade ALLE benötigten Timeframes (Haupt + Untergeordnete) vorab
        all_needed_timeframes = set(timeframes_to_test)
        for tf in timeframes_to_test:
            ltf = get_lower_timeframe(tf)
            if ltf: all_needed_timeframes.add(ltf)
        
        print(f"Lade Daten für Timeframes: {', '.join(all_needed_timeframes)}")
        full_data_cache = {tf: load_data_for_backtest(base_params['symbol'], tf, start_date, end_date) for tf in all_needed_timeframes}
        
        main_data_cache = {tf: full_data_cache[tf] for tf in timeframes_to_test}
        ltf_data_cache = {tf: full_data_cache.get(tf) for tf in all_needed_timeframes if tf not in timeframes_to_test}

        results_df = run_single_optimization_pass(param_combinations, base_params, initial_capital, main_data_cache, ltf_data_cache, start_date, end_date)
        
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
            print("\n  GEFUNDENE OPTIMALE PARAMETER:")
            print(f"    Risiko pro Trade:   {row['risk_per_trade_percent']}%")
            print(f"    Hebel-Spanne:       {row['min_leverage']:.1f}x (Min) / {row['base_leverage']:.1f}x (Base) / {row['max_leverage']:.1f}x (Max)")
            print(f"    Vola-Sensitivität:  {row['ltf_vol_sensitivity']:.1f}")
            print(f"    SL Multiplikator:   {row['stop_loss_atr_multiplier']}")
            print(f"    Trailing Stop:      {row['trailing_tp_percent']:.2f}%")
            print(f"    Timeframe:          {row['timeframe']}")
            print(f"    UT ATR Periode:     {int(row['ut_atr_period'])}")
            print(f"    UT Key Value:       {row['ut_key_value']:.1f}")
        
    # (Finale Gesamtauswertung bleibt unverändert)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategie-Optimierer mit Multi-Timeframe-Analyse.")
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--timeframes', required=True)
    parser.add_argument('--symbols', nargs='+')
    parser.add_argument('--risk', type=float, dest='risk_percent')
    parser.add_argument('--initial_capital', type=float, default=1000)
    parser.add_argument('--top', type=int, default=10)
    args = parser.parse_args()
    run_optimization(args.start, args.end, args.timeframes, args.symbols, args.risk_percent, initial_capital=args.initial_capital, top_n=args.top)
