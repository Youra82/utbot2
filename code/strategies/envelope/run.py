# run.py
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
import pytz
import time
import logging
from datetime import datetime, timedelta, timezone

# Pfad für Modulimporte
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from utilities.bitget_futures import BitgetFutures

# --- KONFIGURATION MIT DETAILBESCHREIBUNGEN ---
params = {
    'symbol': 'BTC/USDT:USDT',
    'timeframe': '15m',
    'margin_mode': 'isolated',
    'balance_fraction': 1,
    'leverage': 1,
    'use_longs': True,
    'use_shorts': True,
    'stop_loss_pct': 0.4,
    'enable_stop_loss': True,
    'signal_lookback_period': 6,
    'min_signal_confirmation': 0.2,
    'ut_key_value': 1,
    'ut_atr_period': 10,
    'ut_heiken_ashi': False,
    'trade_size_pct': 100,
    'max_retries': 3,
    'retry_delay': 2,
}

# --- PFADEINSTELLUNGEN ---
key_path = '/home/ubuntu/utbot2/secret.json'
key_name = 'envelope'
tracker_file = f"/home/ubuntu/utbot2/code/strategies/envelope/tracker_{params['symbol'].replace('/', '-').replace(':', '-')}.json"

# --- LOGGING EINRICHTEN ---
log_dir = '/home/ubuntu/utbot2/logs'
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'envelope.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s UTC: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('envelope_bot')

# --------------------------
# --- MONITORAUSGABE: VORZEITIGE ZUSAMMENFASSUNG FÜR ZUVERLÄSSIGKEIT ---
logger.info("--- MONITORING ZUSAMMENFASSUNG ---")
logger.info("Eingestellte Parameter:")
for key, value in params.items():
    logger.info(f"- {key}: {value}")
# --------------------------

current_utc = datetime.now(timezone.utc)
logger.info(f">>> starting execution for {params['symbol']}")

# Verbindung mit Wiederholungslogik
def create_bitget_connection():
    for attempt in range(params['max_retries']):
        try:
            with open(key_path, "r") as f:
                api_setup = json.load(f)[key_name]
            bitget = BitgetFutures(api_setup)
            logger.info("API-Verbindung erfolgreich hergestellt")
            return bitget
        except Exception as e:
            logger.error(f"Verbindungsfehler (Versuch {attempt+1}/{params['max_retries']}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: API-Verbindung fehlgeschlagen")
    sys.exit(1)

bitget = create_bitget_connection()

# --- TRACKER-DATEI HANDLING ---
def read_tracker_file(file_path):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": [], "trades_count": 0}

def update_tracker_file(file_path, data):
    with open(file_path, 'w') as file:
        json.dump(data, file)

tracker_info = read_tracker_file(tracker_file)

# --- ORDER MANAGEMENT ---
def cancel_all_orders():
    for attempt in range(params['max_retries']):
        try:
            orders = bitget.fetch_open_orders(params['symbol'])
            for order in orders:
                bitget.cancel_order(order['id'], params['symbol'])
            
            trigger_orders = bitget.fetch_open_trigger_orders(params['symbol'])
            for order in trigger_orders:
                bitget.cancel_trigger_order(order['id'], params['symbol'])
            
            logger.info("Alle Orders erfolgreich storniert")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Stornieren von Orders (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.error("Kritischer Fehler: Orders konnten nicht storniert werden")
    return False

cancel_all_orders()

# --- UT BOT ALERTS LOGIK ---
def calculate_heikin_ashi(data):
    ha_data = pd.DataFrame(index=data.index)
    if not data.empty:
        ha_close = (data['open'] + data['high'] + data['low'] + data['close']) / 4
        ha_open = (data['open'].iloc[0] + data['close'].iloc[0]) / 2
        ha_data['ha_open'] = np.nan
        ha_data['ha_high'] = np.nan
        ha_data['ha_low'] = np.nan
        ha_data['ha_close'] = ha_close
        for i in range(len(data)):
            if i == 0:
                ha_data.iloc[0, ha_data.columns.get_loc('ha_open')] = ha_open
            else:
                ha_open = (ha_data['ha_open'].iloc[i-1] + ha_data['ha_close'].iloc[i-1]) / 2
                ha_data.iloc[i, ha_data.columns.get_loc('ha_open')] = ha_open
            ha_high = max(data['high'].iloc[i], ha_data['ha_open'].iloc[i], ha_data['ha_close'].iloc[i])
            ha_low = min(data['low'].iloc[i], ha_data['ha_open'].iloc[i], ha_data['ha_close'].iloc[i])
            ha_data.iloc[i, ha_data.columns.get_loc('ha_high')] = ha_high
            ha_data.iloc[i, ha_data.columns.get_loc('ha_low')] = ha_low
    return ha_data

def calculate_ut_signals(data, params):
    if params['ut_heiken_ashi']:
        ha_data = calculate_heikin_ashi(data)
        src = ha_data['ha_close']
    else:
        src = data['close']
    data['atr'] = ta.volatility.average_true_range(
        data['high'], data['low'], data['close'], 
        window=params['ut_atr_period']
    )
    n_loss = params['ut_key_value'] * data['atr']
    x_atr_trailing_stop = np.zeros(len(data))
    for i in range(len(data)):
        if i == 0:
            x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
        else:
            if src.iloc[i] > x_atr_trailing_stop[i-1] and src.iloc[i-1] > x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = max(x_atr_trailing_stop[i-1], src.iloc[i] - n_loss.iloc[i])
            elif src.iloc[i] < x_atr_trailing_stop[i-1] and src.iloc[i-1] < x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = min(x_atr_trailing_stop[i-1], src.iloc[i] + n_loss.iloc[i])
            else:
                if src.iloc[i] > x_atr_trailing_stop[i-1]:
                    x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
                else:
                    x_atr_trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    data['ema1'] = src
    data['buy_signal'] = False
    data['sell_signal'] = False
    for i in range(1, len(data)):
        buy_condition = (
            data['ema1'].iloc[i] > data['x_atr_trailing_stop'].iloc[i] and
            data['ema1'].iloc[i-1] <= data['x_atr_trailing_stop'].iloc[i-1] and
            src.iloc[i] > data['x_atr_trailing_stop'].iloc[i]
        )
        sell_condition = (
            data['ema1'].iloc[i] < data['x_atr_trailing_stop'].iloc[i] and
            data['ema1'].iloc[i-1] >= data['x_atr_trailing_stop'].iloc[i-1] and
            src.iloc[i] < data['x_atr_trailing_stop'].iloc[i]
        )
        if buy_condition:
            data.loc[data.index[i], 'buy_signal'] = True
        if sell_condition:
            data.loc[data.index[i], 'sell_signal'] = True
    return data

def log_trade_decision(signal_type, decision_reason, details=None):
    decision_data = {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': params['symbol'],
        'signal': signal_type,
        'decision': decision_reason,
        'details': details or {}
    }
    logger.info(f"TRADE_DECISION: {json.dumps(decision_data)}")

# --- DATEN ABRUFEN UND SIGNALE BERECHNEN ---
def fetch_ohlcv_data():
    for attempt in range(params['max_retries']):
        try:
            now = datetime.now(timezone.utc)
            timeframe_minutes = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '2h': 120, '4h': 240, '1d': 1440}
            candle_duration = timedelta(minutes=timeframe_minutes.get(params['timeframe'], 60))
            seconds_since_candle = (now.minute % timeframe_minutes.get(params['timeframe'], 60) * 60 + now.second)
            
            if seconds_since_candle < 60:
                log_trade_decision('NONE', 'EXECUTION_SKIPPED', {'reason': f"Zu früh in neuer Kerze ({seconds_since_candle}s), überspringe Ausführung"})
                logger.info(f"Zu früh in neuer Kerze ({seconds_since_candle}s), überspringe Ausführung")
                # ACHTUNG: Hier wird beendet, bevor die Parameter am Ende geloggt werden können
                sys.exit()

            lookback_candles = max(100, params['signal_lookback_period'] + 20)
            data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], lookback_candles)
            data.index = data.index.tz_localize('UTC')
            return data
        except Exception as e:
            logger.error(f"Fehler beim Datenabruf (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    log_trade_decision('NONE', 'CRITICAL_ERROR', {'reason': "Daten konnten nicht abgerufen werden"})
    logger.critical("Kritischer Fehler: Daten konnten nicht abgerufen werden")
    sys.exit(1)

data = fetch_ohlcv_data()
data = calculate_ut_signals(data, params)

logger.info("\nLetzte 10 Kerzen Signale und Indikatoren:")
logger.info(data[['open', 'high', 'low', 'close', 'atr', 'x_atr_trailing_stop', 'buy_signal', 'sell_signal']].tail(10).to_string())

current_time = datetime.now(timezone.utc)
signals = []
timeframe_minutes = {
    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '2h': 120, '4h': 240, '1d': 1440
}
candle_duration = timedelta(minutes=timeframe_minutes.get(params['timeframe'], 60))

for i in range(1, min(params['signal_lookback_period'] + 1, len(data))):
    idx = -i
    candle_time = data.index[idx]
    time_elapsed = current_time - candle_time
    candle_completion = min(1.0, time_elapsed.total_seconds() / candle_duration.total_seconds())
    if candle_completion >= params['min_signal_confirmation']:
        if data.iloc[idx]['buy_signal']:
            signals.append(('buy', candle_time, data.iloc[idx]['close']))
        elif data.iloc[idx]['sell_signal']:
            signals.append(('sell', candle_time, data.iloc[idx]['close']))
    else:
        log_trade_decision('NONE', 'SIGNAL_LOOKBACK_SKIPPED', {
            'reason': f"Kerze bei {candle_time} nicht genug bestätigt (Fortschritt: {candle_completion:.2f})",
            'min_confirmation': params['min_signal_confirmation']
        })

logger.info(f"Gefundene Signale: {len(signals)} in letzten {params['signal_lookback_period']} Kerzen")

buy_signal = False
sell_signal = False
signal_used = None
signal_reason = "Keine Signale erkannt"

if signals:
    latest_signal = signals[-1]
    signal_type, signal_time, signal_price = latest_signal
    current_price = data.iloc[-1]['close']
    signal_reason = f"{signal_type.upper()}-Signal von {signal_time.strftime('%Y-%m-%d %H:%M')} UTC"
    log_trade_decision(signal_type.upper(), 'VALID_SIGNAL', {
        'signal_time': signal_time.strftime('%Y-%m-%d %H:%M:%S'),
        'signal_price': float(signal_price),
        'current_price': float(current_price),
    })
    if signal_type == 'buy':
        buy_signal = True
    else:
        sell_signal = True
    logger.info(f"Verwende {signal_reason}")
else:
    log_trade_decision('NONE', 'NO_SIGNALS_IN_LOOKBACK', {
        'reason': "Kein gültiges Signal im Lookback-Fenster gefunden, das die Bestätigungskriterien erfüllt.",
        'lookback_period': params['signal_lookback_period'],
        'min_confirmation': params['min_signal_confirmation']
    })
    logger.info(signal_reason)

signal_status = "KAUF" if buy_signal else "VERKAUF" if sell_signal else "KEIN SIGNAL"
logger.info(f"Signalanalyse abgeschlossen: {signal_status} - {signal_reason}")

def fetch_positions():
    for attempt in range(params['max_retries']):
        try:
            positions = bitget.fetch_open_positions(params['symbol'])
            return positions
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Positionen (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.error("Kritischer Fehler: Positionen konnten nicht abgerufen werden")
    return []

positions = fetch_positions()
open_position = len(positions) > 0

if open_position:
    position = positions[0]
    position_side = position['side']
    position_size = float(position['contracts']) * float(position['contractSize'])
    entry_price = float(position['entryPrice'])
    logger.info(f"Offene {position_side} Position - Größe: {position_size:.4f}, Einstieg: {entry_price:.2f}")
else:
    position_side = None

logger.info(f"\nHandelsentscheidung Zusammenfassung:")
logger.info(f"Kauf-Signal: {buy_signal} | Verkauf-Signal: {sell_signal}")
logger.info(f"Offene Position: {open_position} | Position Seite: {position_side}")
logger.info(f"Longs aktiviert: {params['use_longs']} | Shorts aktiviert: {params['use_shorts']}")

if tracker_info['status'] != "ok_to_trade":
    status_reason = f"Status ist {tracker_info['status']}, überspringe Handel"
    log_trade_decision('NONE', 'TRACKER_STATUS_BLOCKED', {'status': tracker_info['status']})
    logger.info(status_reason)
    sys.exit()

def fetch_balance():
    for attempt in range(params['max_retries']):
        try:
            balance_info = bitget.fetch_balance()
            return balance_info
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Kontostands (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    log_trade_decision('NONE', 'CRITICAL_ERROR', {'reason': "Kontostand konnte nicht abgerufen werden"})
    logger.error("Kritischer Fehler: Kontostand konnte nicht abgerufen werden")
    return {'USDT': {'total': 0}}

def calculate_required_leverage(current_balance, min_trade_size, trade_size_pct):
    if current_balance <= 0:
        return "N/A"
    base_trade_size_without_leverage = current_balance * (trade_size_pct / 100)
    if base_trade_size_without_leverage == 0:
        return "N/A"
    needed_leverage = min_trade_size / base_trade_size_without_leverage
    return needed_leverage

balance_info = fetch_balance()
balance = balance_info['USDT']['total']
trade_size = (balance * params['trade_size_pct'] / 100) * params['leverage']
logger.info(f"Verfügbarer Kontostand: {balance:.2f} USDT, Handelsgröße: {trade_size:.2f} USDT")

min_trade_size = 10
if trade_size < min_trade_size:
    min_required = min_trade_size / (params['trade_size_pct'] / 100 * params['leverage'])
    required_leverage = calculate_required_leverage(balance, min_trade_size, params['trade_size_pct'])
    reason = f"Kontostand zu niedrig! Benötige mindestens {min_required:.2f} USDT für einen Trade (Minimal: {min_trade_size} USDT)."
    if required_leverage != "N/A":
        reason += f" Ein Hebel von {required_leverage:.2f} wäre nötig, um die Mindesttradegröße zu erreichen."
    log_trade_decision('NONE', 'INSUFFICIENT_BALANCE', {
        'current_balance': balance,
        'min_required_balance': min_required,
        'min_trade_size': min_trade_size,
        'required_leverage': required_leverage,
    })
    logger.error(reason)
    sys.exit()

if open_position:
    if (position_side == 'long' and sell_signal) or (position_side == 'short' and buy_signal):
        try:
            current_price = data.iloc[-1]['close']
            bitget.flash_close_position(params['symbol'])
            close_reason = f"Schließe {position_side} Position aufgrund gegenläufigen Signals"
            logger.info(close_reason)
            log_trade_decision(position_side.upper(), 'POSITION_CLOSED', {
                'reason': 'OPPOSITE_SIGNAL',
                'size': position_size,
                'entry_price': entry_price,
                'exit_price': current_price
            })
            open_position = False
            tracker_info = {
                "status": "ok_to_trade",
                "last_side": None,
                "stop_loss_ids": [],
                "trades_count": tracker_info['trades_count'] + 1
            }
            update_tracker_file(tracker_file, tracker_info)
        except Exception as e:
            log_trade_decision(position_side.upper(), 'CLOSE_ERROR', {'error': str(e)})
            logger.error(f"Fehler beim Schließen der Position: {str(e)}")

if not open_position:
    if buy_signal and params['use_longs']:
        try:
            current_price = data.iloc[-1]['close']
            bitget.place_market_order(params['symbol'], 'buy', trade_size)
            action_reason = f"Öffne Long-Position basierend auf {signal_reason}"
            logger.info(action_reason)
            stop_loss_price = None
            if params['enable_stop_loss']:
                stop_loss_price = current_price * (1 - params['stop_loss_pct'])
                sl_order = bitget.place_trigger_market_order(
                    symbol=params['symbol'],
                    side='sell',
                    amount=trade_size,
                    trigger_price=stop_loss_price,
                    reduce=True
                )
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "long",
                    "stop_loss_ids": [sl_order['id']] if sl_order else [],
                    "trades_count": tracker_info['trades_count'] + 1
                }
                update_tracker_file(tracker_file, tracker_info)
                logger.info(f"Stop-Loss gesetzt bei {stop_loss_price:.2f}")
            else:
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "long",
                    "stop_loss_ids": [],
                    "trades_count": tracker_info['trades_count'] + 1
                }
                update_tracker_file(tracker_file, tracker_info)
            log_trade_decision('BUY', 'POSITION_OPENED', {
                'size': trade_size,
                'price': current_price,
                'stop_loss': stop_loss_price
            })
        except Exception as e:
            log_trade_decision('BUY', 'OPEN_ERROR', {'error': str(e)})
            logger.error(f"Fehler beim Öffnen der Long-Position: {str(e)}")
    elif sell_signal and params['use_shorts']:
        try:
            current_price = data.iloc[-1]['close']
            bitget.place_market_order(params['symbol'], 'sell', trade_size)
            action_reason = f"Öffne Short-Position basierend auf {signal_reason}"
            logger.info(action_reason)
            stop_loss_price = None
            if params['enable_stop_loss']:
                stop_loss_price = current_price * (1 + params['stop_loss_pct'])
                sl_order = bitget.place_trigger_market_order(
                    symbol=params['symbol'],
                    side='buy',
                    amount=trade_size,
                    trigger_price=stop_loss_price,
                    reduce=True
                )
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "short",
                    "stop_loss_ids": [sl_order['id']] if sl_order else [],
                    "trades_count": tracker_info['trades_count'] + 1
                }
                update_tracker_file(tracker_file, tracker_info)
                logger.info(f"Stop-Loss gesetzt bei {stop_loss_price:.2f}")
            else:
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "short",
                    "stop_loss_ids": [],
                    "trades_count": tracker_info['trades_count'] + 1
                }
                update_tracker_file(tracker_file, tracker_info)
            log_trade_decision('SELL', 'POSITION_OPENED', {
                'size': trade_size,
                'price': current_price,
                'stop_loss': stop_loss_price
            })
        except Exception as e:
            log_trade_decision('SELL', 'OPEN_ERROR', {'error': str(e)})
            logger.error(f"Fehler beim Öffnen der Short-Position: {str(e)}")
    elif buy_signal and not params['use_longs']:
        log_trade_decision('BUY', 'TRADE_SKIPPED_CONFIG', {'reason': "Kauf-Signal erkannt, aber 'use_longs' ist deaktiviert."})
        logger.info("Kauf-Signal erkannt, aber Long-Positionen sind deaktiviert.")
    elif sell_signal and not params['use_shorts']:
        log_trade_decision('SELL', 'TRADE_SKIPPED_CONFIG', {'reason': "Verkauf-Signal erkannt, aber 'use_shorts' ist deaktiviert."})
        logger.info("Verkauf-Signal erkannt, aber Short-Positionen sind deaktiviert.")
    else:
        log_trade_decision('NONE', 'NO_ACTION_TAKEN', {'reason': "Kein gültiges Signal für eine neue Position vorhanden."})
        logger.info("Kein gültiges Signal für eine neue Position vorhanden.")

if buy_signal or sell_signal:
    action_taken = "Position eröffnet oder Gegenposition geschlossen"
else:
    action_taken = "Keine Aktion durchgeführt"

logger.info(f"Handelsaktion: {action_taken}")
logger.info(f"<<< Ausführung abgeschlossen um {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC\n")

# --------------------------
# --- MONITORAUSGABE: ZUSÄTZLICHE STATISTIKEN AM ENDE ---
logger.info(f"Anzahl erzeugter Signale im Lookback: {len(signals)}")
logger.info(f"Anzahl der Trades seit Beginn: {tracker_info['trades_count']}")

if 'balance' in locals():
    logger.info(f"Aktueller Kontostand: {balance:.2f} USDT")
else:
    logger.info("Kontostand konnte nicht ermittelt werden.")

logger.info("--- ENDE ZUSAMMENFASSUNG ---")
# --------------------------
