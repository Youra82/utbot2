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
    # Handelsinstrument (z.B. BTC/USDT:USDT)
    'symbol': 'BTC/USDT:USDT',
    
    # Zeitrahmen für Kerzendaten (1m, 5m, 15m, 30m, 1h, 4h, 1d)
    'timeframe': '15m',
    
    # Margin-Modus: 'isolated' (isoliert) oder 'crossed' (Cross-Margin)
    'margin_mode': 'isolated',
    
    # Bruchteil des Kontos, der für Trades verwendet wird (0.0 - 1.0)
    'balance_fraction': 1,
    
    # Hebelwirkung für Positionen
    'leverage': 1,
    
    # Long-Positionen aktivieren
    'use_longs': True,
    
    # Short-Positionen aktivieren
    'use_shorts': True,
    
    # Stop-Loss in Prozent vom Einstiegspreis (0.4 = 0.4%)
    'stop_loss_pct': 0.004, # Korrigiert auf 0.4% = 0.004
    
    # Stop-Loss-Orders aktivieren
    'enable_stop_loss': True,
    
    # Anzahl der Kerzen, in denen nach Signalen gesucht wird
    'signal_lookback_period': 6,
    
    # Mindestfortschritt einer Kerze (0.0-1.0), bevor sie für Signale berücksichtigt wird
    'min_signal_confirmation': 0.2,
    
    # Sensitivität des UT-Bot Alerts (Höhere Werte = weniger empfindlich)
    'ut_key_value': 1,
    
    # Periodenlänge für den Average True Range (ATR)
    'ut_atr_period': 10,
    
    # Signale auf Basis von Heikin-Ashi-Kerzen berechnen
    'ut_heikin_ashi': False,
    
    # Prozentsatz des Kontos pro Trade (100 = voller Kontoeinsatz)
    'trade_size_pct': 100,
    
    # Maximale Wiederholungsversuche bei API-Fehlern
    'max_retries': 3,
    
    # Wartezeit zwischen Wiederholungsversuchen in Sekunden
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

# --- AUTHENTIFIZIERUNG ---
current_utc = datetime.now(timezone.utc)
logger.info(f">>> starting execution for {params['symbol']}")

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

# NEU: Margin-Modus und Hebel sofort nach der Verbindung setzen
try:
    bitget.set_margin_mode(params['symbol'], params['margin_mode'])
    bitget.set_leverage(params['symbol'], params['leverage'])
    logger.info(f"Initial: Margin-Modus auf '{params['margin_mode']}' und Hebel auf '{params['leverage']}' gesetzt.")
except Exception as e:
    logger.error(f"Kritischer Fehler: Konnte Margin-Modus oder Hebel nicht einstellen: {e}")
    sys.exit(1)

# --- TRACKER-DATEI HANDLING ---
def read_tracker_file(file_path):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}

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
            
            logger.info("Alle offenen Orders erfolgreich storniert")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Stornieren von Orders (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.error("Kritischer Fehler: Orders konnten nicht storniert werden")
    return False

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
    if params['ut_heikin_ashi']:
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
            data['ema1'].iloc[i-1] <= data['x_atr_trailing_stop'].iloc[i-1]
        )
        
        sell_condition = (
            data['ema1'].iloc[i] < data['x_atr_trailing_stop'].iloc[i] and
            data['ema1'].iloc[i-1] >= data['x_atr_trailing_stop'].iloc[i-1]
        )
        
        if buy_condition:
            data.loc[data.index[i], 'buy_signal'] = True
            
        if sell_condition:
            data.loc[data.index[i], 'sell_signal'] = True
    return data

# --- TRADE-ENTSCHEIDUNGSPROTOKOLL ---
def log_trade_decision(signal_type, decision_code, details=None):
    decision_data = {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': params['symbol'],
        'signal': signal_type,
        'decision_code': decision_code,
        'details': details or {}
    }
    logger.info(f"TRADE_DECISION: {json.dumps(decision_data)}")

# --- DATEN ABRUFEN UND SIGNALE BERECHNEN ---
def fetch_ohlcv_data():
    for attempt in range(params['max_retries']):
        try:
            lookback_candles = max(100, params['signal_lookback_period'] + 20)
            data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], lookback_candles)
            data.index = data.index.tz_localize('UTC')
            return data
        except Exception as e:
            logger.error(f"Fehler beim Datenabruf (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: Daten konnten nicht abgerufen werden")
    sys.exit(1)

data = fetch_ohlcv_data()
data = calculate_ut_signals(data, params)

logger.info("\nLetzte 10 Kerzen Signale und Indikatoren:")
logger.info(data[['open', 'high', 'low', 'close', 'atr', 'x_atr_trailing_stop', 'buy_signal', 'sell_signal']].tail(10).to_string())

current_time = datetime.now(timezone.utc)
signals = []
timeframe_minutes = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '2h': 120, '4h': 240, '1d': 1440}
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

logger.info(f"Gefundene gültige Signale: {len(signals)} in letzten {params['signal_lookback_period']} Kerzen")

buy_signal = False
sell_signal = False
signal_reason = "Kein Signal im Lookback-Zeitraum gefunden."
if signals:
    latest_signal = signals[-1]
    signal_type, signal_time, signal_price = latest_signal
    signal_reason = f"{signal_type.upper()}-Signal von {signal_time.strftime('%Y-%m-%d %H:%M')} UTC"
    
    log_trade_decision(signal_type.upper(), 'VALID_SIGNAL_DETECTED', {
        'signal_time': signal_time.strftime('%Y-%m-%d %H:%M:%S'),
        'signal_price': float(signal_price),
        'current_price': float(data.iloc[-1]['close']),
    })
    logger.info(f"Signal erkannt: {signal_reason}")

# --- OFFENE POSITIONEN PRÜFEN ---
def fetch_positions():
    for attempt in range(params['max_retries']):
        try:
            return bitget.fetch_open_positions(params['symbol'])
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Positionen (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.error("Kritischer Fehler: Positionen konnten nicht abgerufen werden")
    return []

positions = fetch_positions()
open_position = len(positions) > 0

# #############################################################################
# #################### ÜBERARBEITETER HANDELS-LOGIKBLOCK ######################
# #############################################################################

if tracker_info['status'] != "ok_to_trade":
    reason = f"Tracker-Status ist '{tracker_info['status']}'"
    log_trade_decision('NONE', 'TRADE_SKIPPED_TRACKER_STATUS', {'reason': reason})
    logger.warning(f"Handel übersprungen: {reason}")
    sys.exit()

if not buy_signal and not sell_signal:
    log_trade_decision('NONE', 'NO_VALID_SIGNAL', {'lookback_period': params['signal_lookback_period'], 'min_confirmation': params['min_signal_confirmation']})
    logger.info("Kein aktives Handelssignal gefunden. Beende Ausführung.")
    sys.exit()

if open_position:
    position_side = positions[0]['side']
    position_size = float(positions[0]['contracts']) * float(positions[0]['contractSize'])
    entry_price = float(positions[0]['entryPrice'])
    logger.info(f"Bestehende offene Position gefunden: {position_side.upper()} | Größe: {position_size:.4f} | Einstieg: {entry_price:.2f}")

    if (position_side == 'long' and sell_signal) or (position_side == 'short' and buy_signal):
        logger.info(f"Gegenläufiges Signal ({'Verkauf' if sell_signal else 'Kauf'}) erkannt. Schließe offene {position_side}-Position.")
        try:
            current_price = data.iloc[-1]['close']
            bitget.flash_close_position(params['symbol'])
            log_trade_decision(position_side.upper(), 'POSITION_CLOSED_DUE_TO_OPPOSITE_SIGNAL', {'exit_price': current_price})
            logger.info("Position erfolgreich geschlossen, mache Platz für neuen Trade.")
            open_position = False
            update_tracker_file(tracker_file, {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []})
        except Exception as e:
            log_trade_decision(position_side.upper(), 'POSITION_CLOSE_ERROR', {'error': str(e)})
            logger.error(f"Kritischer Fehler beim Schließen der Position: {str(e)}")
            sys.exit()
    else:
        reason = f"Ein {'Kauf' if buy_signal else 'Verkauf'}-Signal wurde erkannt, aber es besteht bereits eine offene {position_side}-Position in die gleiche Richtung."
        log_trade_decision('NONE', 'TRADE_SKIPPED_ALREADY_IN_POSITION', {'signal': 'buy' if buy_signal else 'sell', 'position_side': position_side})
        logger.info(reason + " Keine Aktion erforderlich.")
        sys.exit()

if buy_signal and not params['use_longs']:
    log_trade_decision('BUY', 'TRADE_SKIPPED_STRATEGY_DISABLED', {'reason': "Long-Positionen sind in den Parametern deaktiviert ('use_longs': False)."})
    logger.warning("Kaufsignal ignoriert, da Long-Positionen deaktiviert sind.")
    sys.exit()

if sell_signal and not params['use_shorts']:
    log_trade_decision('SELL', 'TRADE_SKIPPED_STRATEGY_DISABLED', {'reason': "Short-Positionen sind in den Parametern deaktiviert ('use_shorts': False)."})
    logger.warning("Verkaufssignal ignoriert, da Short-Positionen deaktiviert sind.")
    sys.exit()

def fetch_balance():
    """Holt Kontostand mit Wiederholungslogik"""
    for attempt in range(params['max_retries']):
        try:
            balance_info = bitget.fetch_balance()
            return balance_info
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Kontostands (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.error("Kritischer Fehler: Kontostand konnte nicht abgerufen werden")
    return {'USDT': {'total': 0.0}}

logger.info("Prüfe Kontostand und Mindesthandelsgröße...")
balance_info = fetch_balance()
balance = balance_info.get('USDT', {}).get('total', 0.0)
trade_size_usdt = (balance * (params['trade_size_pct'] / 100)) * params['leverage']

logger.info(f"Verfügbarer Kontostand: {balance:.2f} USDT")
logger.info(f"Geplante Handelsgröße (inkl. Hebel {params['leverage']}x): {trade_size_usdt:.2f} USDT")

try:
    min_trade_cost = bitget.fetch_min_cost(params['symbol'])
except Exception as e:
    logger.error(f"Konnte minimale Handelskosten nicht abrufen: {e}. Verwende Fallback von 5 USDT.")
    min_trade_cost = 5.0

logger.info(f"Minimale erforderliche Handelsgröße (Kosten): {min_trade_cost:.2f} USDT")

if trade_size_usdt < min_trade_cost:
    capital_base = balance * (params['trade_size_pct'] / 100)
    details = {}
    if capital_base > 0:
        required_leverage = min_trade_cost / capital_base
        suggested_leverage = int(np.ceil(required_leverage))
        reason = f"Handelsgröße ({trade_size_usdt:.2f} USDT) liegt unter dem Minimum ({min_trade_cost:.2f} USDT)."
        details = {
            'current_balance': balance,
            'current_trade_size_usdt': trade_size_usdt,
            'min_trade_cost_usdt': min_trade_cost,
            'message': "Guthaben mit aktuellem Hebel nicht ausreichend.",
            'suggested_leverage': f"Um zu handeln, wäre ein Hebel von mindestens {suggested_leverage}x nötig."
        }
    else:
        reason = "Kontostand ist 0."
        details = {'current_balance': balance, 'message': "Kein Guthaben zum Handeln vorhanden."}

    log_trade_decision('NONE', 'INSUFFICIENT_FUNDS', details)
    logger.error(f"FEHLER: {reason}")
    if 'suggested_leverage' in details:
        logger.info(details['suggested_leverage'])
    sys.exit()

logger.info("Kontostand und Handelsgröße sind ausreichend. Fahre mit Trade-Ausführung fort.")

action_taken = "Keine Aktion durchgeführt"
if buy_signal and params['use_longs']:
    try:
        current_price = data.iloc[-1]['close']
        amount_to_trade = trade_size_usdt / current_price
        bitget.place_market_order(params['symbol'], 'buy', amount_to_trade)
        action_reason = f"Öffne Long-Position basierend auf {signal_reason}"
        logger.info(action_reason)
        
        stop_loss_price = None
        if params['enable_stop_loss']:
            stop_loss_price = current_price * (1 - params['stop_loss_pct'])
            sl_order = bitget.place_trigger_market_order(
                symbol=params['symbol'], side='sell', amount=amount_to_trade,
                trigger_price=stop_loss_price, reduce=True
            )
            tracker_info = {"status": "in_trade", "last_side": "long", "stop_loss_ids": [sl_order['id']] if sl_order else []}
            logger.info(f"Stop-Loss für Long-Position gesetzt bei {stop_loss_price:.2f}")
        else:
            tracker_info = {"status": "in_trade", "last_side": "long", "stop_loss_ids": []}
        
        update_tracker_file(tracker_file, tracker_info)
        log_trade_decision('BUY', 'POSITION_OPENED', {'size_usdt': trade_size_usdt, 'price': current_price, 'stop_loss': stop_loss_price})
        action_taken = f"Long-Position eröffnet"
    except Exception as e:
        log_trade_decision('BUY', 'POSITION_OPEN_ERROR', {'error': str(e)})
        logger.error(f"Fehler beim Öffnen der Long-Position: {str(e)}")

elif sell_signal and params['use_shorts']:
    try:
        current_price = data.iloc[-1]['close']
        amount_to_trade = trade_size_usdt / current_price
        bitget.place_market_order(params['symbol'], 'sell', amount_to_trade)
        action_reason = f"Öffne Short-Position basierend auf {signal_reason}"
        logger.info(action_reason)
        
        stop_loss_price = None
        if params['enable_stop_loss']:
            stop_loss_price = current_price * (1 + params['stop_loss_pct'])
            sl_order = bitget.place_trigger_market_order(
                symbol=params['symbol'], side='buy', amount=amount_to_trade,
                trigger_price=stop_loss_price, reduce=True
            )
            tracker_info = {"status": "in_trade", "last_side": "short", "stop_loss_ids": [sl_order['id']] if sl_order else []}
            logger.info(f"Stop-Loss für Short-Position gesetzt bei {stop_loss_price:.2f}")
        else:
            tracker_info = {"status": "in_trade", "last_side": "short", "stop_loss_ids": []}

        update_tracker_file(tracker_file, tracker_info)
        log_trade_decision('SELL', 'POSITION_OPENED', {'size_usdt': trade_size_usdt, 'price': current_price, 'stop_loss': stop_loss_price})
        action_taken = f"Short-Position eröffnet"
    except Exception as e:
        log_trade_decision('SELL', 'POSITION_OPEN_ERROR', {'error': str(e)})
        logger.error(f"Fehler beim Öffnen der Short-Position: {str(e)}")

logger.info(f"Handelsaktion: {action_taken}")
logger.info(f"<<< Ausführung abgeschlossen um {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
