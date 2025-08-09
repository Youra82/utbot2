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
    'stop_loss_pct': 0.4,
    
    # Stop-Loss-Orders aktivieren
    'enable_stop_loss': True,
    
    # Anzahl der Kerzen, in denen nach Signalen gesucht wird
    'signal_lookback_period': 6,
    
    # Mindestfortschritt einer Kerze (0.0-1.0), bevor sie für Signale berücksichtigt wird
    'min_signal_confirmation': 0.2,
    
    # Maximale Preisänderung (%) seit Signalgenerierung für gültiges Signal
    'max_price_change_pct': 2.5,
    
    # Sensitivität des UT-Bot Alerts (Höhere Werte = weniger empfindlich)
    'ut_key_value': 1,
    
    # Periodenlänge für den Average True Range (ATR)
    'ut_atr_period': 10,
    
    # Signale auf Basis von Heikin-Ashi-Kerzen berechnen
    'ut_heiken_ashi': False,
    
    # Prozentsatz des Kontos pro Trade (100 = voller Kontoeinsatz)
    'trade_size_pct': 100,
    
    # Maximale Wiederholungsversuche bei API-Fehlern
    'max_retries': 3,
    
    # Wartezeit zwischen Wiederholungsversuchen in Sekunden
    'retry_delay': 2,
}

# --- PFADEINSTELLUNGEN ---
# Absoluter Pfad zur API-Schlüsseldatei
key_path = '/home/ubuntu/utbot2/secret.json'

# Schlüsselname in der secret.json
key_name = 'envelope'

# Tracker-Datei mit absolutem Pfad (speichert Handelsstatus)
tracker_file = f"/home/ubuntu/utbot2/code/strategies/envelope/tracker_{params['symbol'].replace('/', '-').replace(':', '-')}.json"

# --- LOGGING EINRICHTEN ---
log_dir = '/home/ubuntu/utbot2/logs'
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'envelope.log')

# Logger-Konfiguration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s UTC: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('envelope_bot')

# --- AUTHENTIFIZIERUNG ---
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
        return {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}

def update_tracker_file(file_path, data):
    with open(file_path, 'w') as file:
        json.dump(data, file)

# Tracker initialisieren
tracker_info = read_tracker_file(tracker_file)

# --- ORDER MANAGEMENT ---
def cancel_all_orders():
    for attempt in range(params['max_retries']):
        try:
            # Stoppe alle aktiven Orders
            orders = bitget.fetch_open_orders(params['symbol'])
            for order in orders:
                bitget.cancel_order(order['id'], params['symbol'])
            
            # Stoppe alle Trigger-Orders
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

# Alle bestehenden Orders stornieren
cancel_all_orders()

# --- UT BOT ALERTS LOGIK ---
def calculate_heikin_ashi(data):
    """Berechnet Heikin-Ashi-Kerzen aus OHLCV-Daten"""
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
    """Berechnet Trading-Signale basierend auf UT-Bot-Algorithmus"""
    if params['ut_heiken_ashi']:
        ha_data = calculate_heikin_ashi(data)
        src = ha_data['ha_close']
    else:
        src = data['close']
    
    # ATR berechnen
    data['atr'] = ta.volatility.average_true_range(
        data['high'], data['low'], data['close'], 
        window=params['ut_atr_period']
    )
    
    n_loss = params['ut_key_value'] * data['atr']
    
    # Trailing Stop berechnen
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
    data['ema1'] = src  # EMA(1) entspricht dem Preis
    
    # Signale generieren (exakt wie in TradingView)
    data['buy_signal'] = False
    data['sell_signal'] = False
    
    for i in range(1, len(data)):
        # TradingView: (ema > stop) and (ema[1] <= stop[1])
        buy_condition = (
            data['ema1'].iloc[i] > data['x_atr_trailing_stop'].iloc[i] and
            data['ema1'].iloc[i-1] <= data['x_atr_trailing_stop'].iloc[i-1] and
            src.iloc[i] > data['x_atr_trailing_stop'].iloc[i]
        )
        
        # TradingView: (ema < stop) and (ema[1] >= stop[1])
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

# --- TRADE-ENTSCHEIDUNGSPROTOKOLL ---
def log_trade_decision(signal_type, decision_reason, details=None):
    """Protokolliert Handelsentscheidungen im JSON-Format"""
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
    """Holt OHLCV-Daten mit Wiederholungslogik"""
    for attempt in range(params['max_retries']):
        try:
            # Warte bis Kerze mindestens 1 Minute alt ist (für 15m-Kerzen)
            now = datetime.now(timezone.utc)
            candle_duration = timedelta(minutes=15)
            seconds_since_candle = (now.minute % 15 * 60 + now.second) if now.minute >= 0 else 0

            if seconds_since_candle < 60:
                logger.info(f"Zu früh in neuer Kerze ({seconds_since_candle}s), überspringe Ausführung")
                sys.exit()

            # Mehr Kerzen holen für Rückblick
            lookback_candles = max(100, params['signal_lookback_period'] + 20)
            data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], lookback_candles)
            
            # Zeitzonen für Index setzen
            data.index = data.index.tz_localize('UTC')
            return data
        except Exception as e:
            logger.error(f"Fehler beim Datenabruf (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: Daten konnten nicht abgerufen werden")
    sys.exit(1)

# OHLCV-Daten abrufen
data = fetch_ohlcv_data()
data = calculate_ut_signals(data, params)

# Diagnostische Ausgabe
logger.info("\nLetzte 10 Kerzen Signale und Indikatoren:")
logger.info(data[['open', 'high', 'low', 'close', 'atr', 'x_atr_trailing_stop', 'buy_signal', 'sell_signal']].tail(10).to_string())

# Signalerkennung
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
    
    # Kerzenfortschritt prüfen
    time_elapsed = current_time - candle_time
    candle_completion = min(1.0, time_elapsed.total_seconds() / candle_duration.total_seconds())
    
    # Nur signifikant fortgeschrittene Kerzen berücksichtigen
    if candle_completion >= params['min_signal_confirmation']:
        if data.iloc[idx]['buy_signal']:
            signals.append(('buy', candle_time, data.iloc[idx]['close']))
        elif data.iloc[idx]['sell_signal']:
            signals.append(('sell', candle_time, data.iloc[idx]['close']))

logger.info(f"Gefundene Signale: {len(signals)} in letzten {params['signal_lookback_period']} Kerzen")

# Entscheidungslogik
buy_signal = False
sell_signal = False
signal_used = None
signal_reason = "Keine Signale erkannt"

if signals:
    latest_signal = signals[-1]
    signal_type, signal_time, signal_price = latest_signal
    
    current_price = data.iloc[-1]['close']
    price_change = abs(current_price - signal_price) / signal_price * 100
    
    if price_change < params['max_price_change_pct']:
        if signal_type == 'buy':
            log_trade_decision('BUY', 'VALID_SIGNAL', {
                'signal_price': float(signal_price),
                'current_price': float(current_price),
                'price_change_pct': float(price_change),
                'max_allowed_change': params['max_price_change_pct']
            })
            buy_signal = True
            signal_reason = f"Kauf-Signal von {signal_time.strftime('%Y-%m-%d %H:%M')} UTC (Δ: {price_change:.2f}%)"
        else:
            log_trade_decision('SELL', 'VALID_SIGNAL', {
                'signal_price': float(signal_price),
                'current_price': float(current_price),
                'price_change_pct': float(price_change),
                'max_allowed_change': params['max_price_change_pct']
            })
            sell_signal = True
            signal_reason = f"Verkauf-Signal von {signal_time.strftime('%Y-%m-%d %H:%M')} UTC (Δ: {price_change:.2f}%)"
        logger.info(f"Verwende {signal_reason}")
    else:
        log_trade_decision(signal_type.upper(), 'PRICE_CHANGE_TOO_HIGH', {
            'signal_price': float(signal_price),
            'current_price': float(current_price),
            'price_change_pct': float(price_change),
            'threshold': params['max_price_change_pct']
        })
        signal_reason = f"Signal abgelaufen (Δ {price_change:.2f}% > Limit {params['max_price_change_pct']}%)"
        logger.info(signal_reason)
else:
    log_trade_decision('NONE', 'NO_SIGNALS_IN_LOOKBACK', {
        'lookback_period': params['signal_lookback_period'],
        'min_confirmation': params['min_signal_confirmation']
    })
    logger.info(signal_reason)

# Signalzusammenfassung für Monitoring
signal_status = "KAUF" if buy_signal else "VERKAUF" if sell_signal else "KEIN SIGNAL"
logger.info(f"Signalanalyse abgeschlossen: {signal_status} - {signal_reason}")

# --- OFFENE POSITIONEN PRÜFEN ---
def fetch_positions():
    """Holt offene Positionen mit Wiederholungslogik"""
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

# Debug-Info
logger.info(f"\nHandelsentscheidung Zusammenfassung:")
logger.info(f"Kauf-Signal: {buy_signal} | Verkauf-Signal: {sell_signal}")
logger.info(f"Offene Position: {open_position} | Position Seite: {position_side}")
logger.info(f"Longs aktiviert: {params['use_longs']} | Shorts aktiviert: {params['use_shorts']}")

# --- HANDEL AUSFÜHREN ---
if tracker_info['status'] != "ok_to_trade":
    status_reason = f"Status ist {tracker_info['status']}, überspringe Handel"
    logger.info(status_reason)
    sys.exit()

# Kontostand abrufen
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
    return {'USDT': {'total': 0}}

balance_info = fetch_balance()
balance = balance_info['USDT']['total']
trade_size = (balance * params['trade_size_pct'] / 100) * params['leverage']
logger.info(f"Verfügbarer Kontostand: {balance:.2f} USDT, Handelsgröße: {trade_size:.2f} USDT")

# Gegenläufige Position schließen
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
            
            # Aktualisiere Tracker
            tracker_info = {
                "status": "ok_to_trade",
                "last_side": None,
                "stop_loss_ids": []
            }
            update_tracker_file(tracker_file, tracker_info)
        except Exception as e:
            log_trade_decision(position_side.upper(), 'CLOSE_ERROR', {'error': str(e)})
            logger.error(f"Fehler beim Schließen der Position: {str(e)}")

# Neue Position eröffnen
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
                    "stop_loss_ids": [sl_order['id']] if sl_order else []
                }
                update_tracker_file(tracker_file, tracker_info)
                logger.info(f"Stop-Loss gesetzt bei {stop_loss_price:.2f}")
            else:
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "long",
                    "stop_loss_ids": []
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
                    "stop_loss_ids": [sl_order['id']] if sl_order else []
                }
                update_tracker_file(tracker_file, tracker_info)
                logger.info(f"Stop-Loss gesetzt bei {stop_loss_price:.2f}")
            else:
                tracker_info = {
                    "status": "ok_to_trade",
                    "last_side": "short",
                    "stop_loss_ids": []
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

# Handelszusammenfassung für Monitoring
if buy_signal or sell_signal:
    action_taken = "Position eröffnet" if not open_position else "Gegenposition geschlossen"
else:
    action_taken = "Keine Aktion durchgeführt"

logger.info(f"Handelsaktion: {action_taken}")
logger.info(f"<<< Ausführung abgeschlossen um {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC\n")
