# code/utilities/data_loader.py
import os
import sys
import json
import pandas as pd
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))
from bitget_futures import BitgetFutures

def load_data_for_backtest(symbol, timeframe, start_date_str, end_date_str, hide_messages=False):
    project_root = Path(__file__).parent.parent
    cache_dir = project_root / 'analysis' / 'historical_data'
    os.makedirs(cache_dir, exist_ok=True)
    symbol_filename = symbol.replace('/', '-').replace(':', '-')
    cache_file = cache_dir / f"{symbol_filename}_{timeframe}.csv"
    
    data = None
    if start_date_str and end_date_str and os.path.exists(cache_file):
        if not hide_messages: print(f"Lade Daten aus lokaler Cache-Datei: {cache_file}")
        data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        data.index = pd.to_datetime(data.index, utc=True)

    download_start_date = start_date_str
    if data is not None and not data.empty and end_date_str:
        last_cached_date = data.index[-1].strftime('%Y-%m-%d')
        if not hide_messages: print(f"Letztes Datum im Cache: {last_cached_date}")
        if pd.to_datetime(last_cached_date, utc=True) < pd.to_datetime(end_date_str, utc=True):
            interval_minutes = 0
            if 'm' in timeframe: interval_minutes = int(timeframe.replace('m', ''))
            elif 'h' in timeframe: interval_minutes = int(timeframe.replace('h', '')) * 60
            download_start_date = (data.index[-1] + pd.Timedelta(minutes=interval_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            if not hide_messages: print("Cache ist aktuell.")
            download_start_date = None

    if download_start_date:
        if not hide_messages: print(f"Lade neue Daten von {download_start_date} bis {end_date_str} für {symbol}...")
        try:
            key_path = Path.home() / 'utbot2' / 'secret.json'
            with open(key_path, "r") as f: api_setup = json.load(f)['envelope']
            bitget = BitgetFutures(api_setup)
            new_data = bitget.fetch_historical_ohlcv(symbol, timeframe, download_start_date, end_date_str)
            if new_data is not None and not new_data.empty:
                data = pd.concat([data, new_data]) if data is not None else new_data
                data = data[~data.index.duplicated(keep='first')]
                data.sort_index(inplace=True)
                data.to_csv(cache_file)
                if not hide_messages: print("Cache-Datei wurde aktualisiert.")
        except Exception as e:
            if not hide_messages: print(f"\nFehler beim Daten-Download: {e}")
            return None
            
    if data is not None and not data.empty:
        if start_date_str and end_date_str:
             return data.loc[start_date_str:end_date_str]
        return data
    
    # Fallback, wenn keine historischen Daten da sind (für Live-Bot)
    try:
        key_path = Path.home() / 'utbot2' / 'secret.json'
        with open(key_path, "r") as f: api_setup = json.load(f)['envelope']
        bitget = BitgetFutures(api_setup)
        return bitget.fetch_recent_ohlcv(symbol, timeframe, limit=100)
    except Exception as e:
        print(f"Finaler Fehler beim Datenladen: {e}")
        return None
