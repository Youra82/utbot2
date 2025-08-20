# code/analysis/backtest.py
import os
import sys
import json
import pandas as pd
import argparse

# Pfad anpassen
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utilities.bitget_futures import BitgetFutures
from utilities.strategy_logic import calculate_signals

def run_backtest(data, params, verbose=True):
    if verbose:
        print("\nFühre Backtest aus...")

    # Parameter aus der Konfiguration laden
    leverage = params.get('leverage', 1.0)
    sl_multiplier = params.get('stop_loss_atr_multiplier', 1.5)
    
    # Initialisierung der Backtest-Variablen
    in_position = False
    position_side = None
    entry_price = 0.0
    stop_loss_price = 0.0
    total_pnl = 0.0
    trades_count = 0
    wins_count = 0
    
    # Variable zur Speicherung des höchsten kritischen Hebels, der im Test auftritt
    highest_critical_leverage = 0.0 
    
    # Handelsgebühren (z.B. 0.05%)
    fee_pct = 0.05 / 100

    # Hauptschleife über alle Kerzen der historischen Daten
    for i in range(1, len(data)):
        prev_candle = data.iloc[i-1]
        current_candle = data.iloc[i]

        # --- 1. PRÜFUNG: WURDE EIN STOP-LOSS AUSGELÖST? ---
        if in_position:
            pnl = 0.0
            exit_price = 0.0

            # Stop-Loss für eine Long-Position
            if position_side == 'long' and current_candle['low'] <= stop_loss_price:
                exit_price = stop_loss_price
                pnl = (((exit_price - entry_price) / entry_price) * leverage) - (2 * fee_pct * leverage)
                
                # Berechnung des kritischen Hebels basierend auf dem maximalen Kursrückgang
                max_loss_pct = (entry_price - current_candle['low']) / entry_price
                critical_leverage = 1 / max_loss_pct if max_loss_pct > 0 else float('inf')
                highest_critical_leverage = max(highest_critical_leverage, critical_leverage)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | STOP-LOSS   | PnL: {pnl*100:.2f}% | Kritischer Hebel: {critical_leverage:.1f}x")
            
            # Stop-Loss für eine Short-Position
            elif position_side == 'short' and current_candle['high'] >= stop_loss_price:
                exit_price = stop_loss_price
                pnl = (((entry_price - exit_price) / entry_price) * leverage) - (2 * fee_pct * leverage)

                # Berechnung des kritischen Hebels basierend auf dem maximalen Kursanstieg
                max_loss_pct = (current_candle['high'] - entry_price) / entry_price
                critical_leverage = 1 / max_loss_pct if max_loss_pct > 0 else float('inf')
                highest_critical_leverage = max(highest_critical_leverage, critical_leverage)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | STOP-LOSS   | PnL: {pnl*100:.2f}% | Kritischer Hebel: {critical_leverage:.1f}x")

            # Wenn ein Stop-Loss ausgelöst wurde, Trade abschließen und zur nächsten Kerze springen
            if exit_price > 0:
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                in_position = False
                stop_loss_price = 0.0
                continue 

        # --- 2. PRÜFUNG: GIBT ES EIN REGULÄRES AUSSTIEGSSIGNAL (GEGENSIGNAL)? ---
        if in_position:
            exit_price = current_candle['open'] # Ausstieg am Anfang der neuen Kerze
            pnl = 0.0

            # Ausstiegssignal für eine Long-Position
            if position_side == 'long' and prev_candle['sell_signal_ut']:
                pnl = (((exit_price - entry_price) / entry_price) * leverage) - (2 * fee_pct * leverage)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | CLOSE LONG  | PnL: {pnl*100:.2f}%")

            # Ausstiegssignal für eine Short-Position
            elif position_side == 'short' and prev_candle['buy_signal_ut']:
                pnl = (((entry_price - exit_price) / entry_price) * leverage) - (2 * fee_pct * leverage)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | CLOSE SHORT | PnL: {pnl*100:.2f}%")

            # Wenn ein Gegensignal kam, Trade abschließen
            if pnl != 0.0:
                total_pnl += pnl
                trades_count += 1
                if pnl > 0: wins_count += 1
                in_position = False

        # --- 3. PRÜFUNG: GIBT ES EIN EINSTIEGSSIGNAL? ---
        if not in_position:
            entry_price = current_candle['open']
            atr_for_sl = prev_candle['atr']

            # Einstiegssignal für eine Long-Position
            if prev_candle['buy_signal'] and params.get('use_longs', True):
                in_position = True
                position_side = 'long'
                stop_loss_price = entry_price - (atr_for_sl * sl_multiplier)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | OPEN LONG   | @ {entry_price:.2f} | SL: {stop_loss_price:.2f}")

            # Einstiegssignal für eine Short-Position
            elif prev_candle['sell_signal'] and params.get('use_shorts', True):
                in_position = True
                position_side = 'short'
                stop_loss_price = entry_price + (atr_for_sl * sl_multiplier)
                if verbose: print(f"{current_candle.name.strftime('%Y-%m-%d %H:%M')} | OPEN SHORT  | @ {entry_price:.2f} | SL: {stop_loss_price:.2f}")

    # Berechnung der finalen Statistiken
    win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
    
    # Ausgabe der Endergebnisse
    if verbose:
        print("\n--- Backtest-Ergebnisse ---")
        print(f"Zeitraum: {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")
        if 'symbol_display' in params:
            print(f"Symbol: {params['symbol_display']}")
        print(f"Timeframe: {params['timeframe']}")
        print(f"Hebel: {leverage}x | SL-Multiplikator: {sl_multiplier}")
        print(f"Parameter: ut_atr_period={params['ut_atr_period']}, ut_key_value={params['ut_key_value']}, adx_threshold={params.get('adx_threshold', 'N/A')}")
        print("-" * 27)
        print(f"Gesamt-PnL (gehebelt): {total_pnl * 100:.2f}%")
        print(f"Anzahl Trades: {trades_count}")
        print(f"Gewonnene Trades: {wins_count}")
        print(f"Trefferquote: {win_rate:.2f}%")
        # Ausgabe der neuen Risikokennzahl
        if highest_critical_leverage > 0:
            print(f"WARNUNG: Höchster kritischer Hebel war {highest_critical_leverage:.1f}x")
        print("---------------------------")

    # Rückgabe der Ergebnisse als Dictionary
    return {
        "total_pnl_pct": total_pnl * 100,
        "trades_count": trades_count,
        "win_rate": win_rate,
        "critical_leverage": highest_critical_leverage,
        "params": params
    }

def load_data_for_backtest(symbol, timeframe, start_date_str, end_date_str):
    """Lädt und cacht historische Daten von Bitget."""
    cache_dir = os.path.join(os.path.dirname(__file__), 'historical_data')
    os.makedirs(cache_dir, exist_ok=True)
    symbol_filename = symbol.replace('/', '-').replace(':', '-')
    cache_file = os.path.join(cache_dir, f"{symbol_filename}_{timeframe}.csv")

    data = None
    if os.path.exists(cache_file):
        print(f"Lade Daten aus lokaler Cache-Datei: {cache_file}")
        data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        data.index = pd.to_datetime(data.index, utc=True)

    download_start_date = start_date_str
    if data is not None and not data.empty:
        last_cached_date = data.index[-1].strftime('%Y-%m-%d')
        print(f"Letztes Datum im Cache: {last_cached_date}")
        # Prüfen, ob neue Daten benötigt werden
        if pd.to_datetime(last_cached_date, utc=True) < pd.to_datetime(end_date_str, utc=True):
            # Berechne das nächste Zeitintervall, um doppelte Einträge zu vermeiden
            interval_minutes = 0
            if 'm' in timeframe:
                interval_minutes = int(timeframe.replace('m', ''))
            elif 'h' in timeframe:
                interval_minutes = int(timeframe.replace('h', '')) * 60
            download_start_date = (data.index[-1] + pd.Timedelta(minutes=interval_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            print("Cache ist aktuell. Keine neuen Daten zum Herunterladen.")
            download_start_date = None

    if download_start_date:
        print(f"Lade neue Daten von {download_start_date} bis {end_date_str} für {symbol}...")
        try:
            # Lade API-Schlüssel
            key_path = '/home/ubuntu/utbot2/secret.json'
            with open(key_path, "r") as f:
                api_setup = json.load(f)['envelope']
            bitget = BitgetFutures(api_setup)
            new_data = bitget.fetch_historical_ohlcv(symbol, timeframe, download_start_date, end_date_str)
            
            if new_data is not None and not new_data.empty:
                data = pd.concat([data, new_data]) if data is not None else new_data
                data = data[~data.index.duplicated(keep='first')] # Duplikate entfernen
                data.sort_index(inplace=True)
                data.to_csv(cache_file)
                print("Cache-Datei wurde aktualisiert.")
            else:
                print("Keine neuen Daten erhalten.")

        except Exception as e:
            print(f"\nEin Fehler beim Herunterladen der Daten ist aufgetreten: {e}")
            return None
    
    # Filtere die Daten auf den exakten angeforderten Zeitraum
    if data is not None and not data.empty:
        return data.loc[start_date_str:end_date_str]
    return None

if __name__ == "__main__":
    # Argument Parser für Kommandozeilen-Argumente
    parser = argparse.ArgumentParser(description="Strategie-Backtest für den Envelope Bot.")
    parser.add_argument('--start', required=True, help="Startdatum im Format YYYY-MM-DD")
    parser.add_argument('--end', required=True, help="Enddatum im Format YYYY-MM-DD")
    parser.add_argument('--timeframe', required=True, help="Timeframe (z.B. 15m, 1h, 4h, 1d)")
    parser.add_argument('--symbols', nargs='+', help="Ein oder mehrere Handelspaare (z.B. BTC ETH SOL), überschreibt die config.json")
    parser.add_argument('--leverage', type=float, help="Optionaler Hebel (z.B. 10)")
    parser.add_argument('--sl_multiplier', type=float, help="Optionaler Stop-Loss ATR Multiplikator (z.B. 1.5)")
    args = parser.parse_args()

    print("Lade Konfiguration...")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'envelope', 'config.json')
    with open(config_path, 'r') as f:
        base_params = json.load(f)
    
    # Bestimme, welche Symbole getestet werden sollen
    symbols_to_test = args.symbols if args.symbols else [base_params['symbol']]

    # Schleife über alle zu testenden Symbole
    for symbol_arg in symbols_to_test:
        
        params = base_params.copy()
        params['timeframe'] = args.timeframe

        # Überschreibe Hebel und SL-Multiplikator, falls über die Kommandozeile angegeben
        if args.leverage:
            params['leverage'] = args.leverage
        if args.sl_multiplier:
            params['stop_loss_atr_multiplier'] = args.sl_multiplier

        # Formatiere das Symbol korrekt (z.B. BTC -> BTC/USDT:USDT)
        raw_symbol = symbol_arg
        if '/' not in raw_symbol:
            formatted_symbol = f"{raw_symbol.upper()}/USDT:USDT"
        else:
            formatted_symbol = raw_symbol.upper()
        
        print(f"\n\n==================== START TEST FÜR: {formatted_symbol} ====================")
        params['symbol'] = formatted_symbol

        # Lade historische Daten für den Backtest
        data_for_backtest = load_data_for_backtest(params['symbol'], args.timeframe, args.start, args.end)
        
        if data_for_backtest is not None and not data_for_backtest.empty:
            params_for_run = params.copy()
            params_for_run['symbol_display'] = params['symbol'] 

            # Berechne die Handelssignale für die geladenen Daten
            data_with_signals = calculate_signals(data_for_backtest, params)
            
            # Führe den Backtest mit den Daten und Signalen durch
            run_backtest(data_with_signals, params_for_run)

        else:
            print(f"Keine Daten für das Symbol {params['symbol']} im angegebenen Zeitraum verfügbar.")
        
        print(f"==================== ENDE TEST FÜR: {formatted_symbol} =====================\n")
