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
import requests

# Pfad für Modulimporte
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from utilities.bitget_futures import BitgetFutures

# --- TELEGRAM-KONFIGURATION (wird später aus secret.json geladen) ---
telegram_bot_token = None
telegram_chat_id = None

# --- TELEGRAM-FUNKTION ---
def send_telegram_message(message):
    global telegram_bot_token, telegram_chat_id
    if not telegram_bot_token or not telegram_chat_id:
        logger.warning("Telegram-Daten in secret.json nicht gefunden. Nachricht wird nicht gesendet.")
        return

    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    payload = {
        'chat_id': telegram_chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    response = None
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status() # Löst einen Fehler für schlechte HTTP-Statuscodes aus
        logger.info("Telegram-Nachricht erfolgreich gesendet.")
    except requests.exceptions.RequestException as e:
        if response is not None and response.status_code == 200:
            logger.info("Telegram-Nachricht erfolgreich gesendet, aber es gab eine nicht-kritische Warnung.")
        else:
            logger.error(f"Kritischer Fehler beim Senden der Telegram-Nachricht: {e}")


# --- KONFIGURATION MIT DETAILBESCHREIBUNGEN ---
params = {
    'symbol': 'BTC/USDT:USDT',
    'timeframe': '15m',
    'margin_mode': 'isolated',
    'balance_fraction': 1,
    'leverage': 10,
    'use_longs': True,
    'use_shorts': True,
    'stop_loss_pct': 0.004,
    'enable_stop_loss': True,
    'signal_lookback_period': 6,
    'min_signal_confirmation': 0.2,
    'ut_key_value': 1,
    'ut_atr_period': 10,
    'ut_heikin_ashi': False,
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

# --- AUTHENTIFIZIERUNG ---
current_utc = datetime.now(timezone.utc)
logger.info(f">>> starting execution for {params['symbol']}")

# --- LADE ZUGANGSDATEN ---
try:
    with open(key_path, "r") as f:
        secrets = json.load(f)
        api_setup = secrets[key_name]
        telegram_setup = secrets.get('telegram', {})
    
    telegram_bot_token = telegram_setup.get('bot_token')
    telegram_chat_id = telegram_setup.get('chat_id')
except FileNotFoundError:
    logger.critical(f"Kritischer Fehler: secret.json nicht unter {key_path} gefunden.")
    sys.exit(1)
except KeyError as e:
    logger.critical(f"Kritischer Fehler: Fehlender Schlüssel '{e}' in secret.json.")
    sys.exit(1)

def create_bitget_connection():
    for attempt in range(params['max_retries']):
        try:
            bitget = BitgetFutures(api_setup)
            logger.info("API-Verbindung erfolgreich hergestellt")
            return bitget
        except Exception as e:
            logger.error(f"Verbindungsfehler (Versuch {attempt+1}/{params['max_retries']}): {str(e)}")
            if attempt < params['max_retries'] - 1:
                time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: API-Verbindung fehlgeschlagen")
    send_telegram_message("❌ *Kritischer Fehler:* API-Verbindung zu Bitget fehlgeschlagen. Bot wird beendet.")
    sys.exit(1)

bitget = create_bitget_connection()

# --- START-SETUP BLOCK ---
try:
    bitget.set_margin_mode(params['symbol'], params['margin_mode'])
    bitget.set_leverage(params['symbol'], params['leverage'])
    logger.info(f"Initial: Margin-Modus auf '{params['margin_mode']}' und Hebel auf '{params['leverage']}' gesetzt.")
except Exception as e:
    if "45117" in str(e) or "margin mode cannot be adjusted" in str(e):
        logger.info("Margin-Modus/Hebel bereits durch offene Position festgelegt. Überspringe Setup.")
    else:
        logger.error(f"Kritischer Fehler: Konnte Margin-Modus oder Hebel nicht einstellen: {e}")
        send_telegram_message(f"❌ *Kritischer Fehler:* Margin-Modus/Hebel konnte nicht eingestellt werden: {e}")
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

# --- UT BOT ALERTS LOGIK ---
def calculate_ut_signals(data, params):
    src = data['close']
    data['atr'] = ta.volatility.average_true_range(data['high'], data['low'], data['close'], window=params['ut_atr_period'])
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
    data['buy_signal'] = (data['ema1'] > data['x_atr_trailing_stop']) & (data['ema1'].shift(1) <= data['x_atr_trailing_stop'].shift(1))
    data['sell_signal'] = (data['ema1'] < data['x_atr_trailing_stop']) & (data['ema1'].shift(1) >= data['x_atr_trailing_stop'].shift(1))
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

# --- DATEN- UND KONTO-FUNKTIONEN ---
def fetch_balance():
    for attempt in range(params['max_retries']):
        try: return bitget.fetch_balance()
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Kontostands (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1: time.sleep(params['retry_delay'])
    return {'USDT': {'total': 0.0}}

def fetch_ohlcv_data():
    for attempt in range(params['max_retries']):
        try:
            data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], 100)
            data.index = data.index.tz_localize('UTC')
            return data
        except Exception as e:
            logger.error(f"Fehler beim Datenabruf (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1: time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: Daten konnten nicht abgerufen werden")
    sys.exit(1)

# --- SIGNALE BERECHNEN ---
data = fetch_ohlcv_data()
data = calculate_ut_signals(data, params)
logger.info("\nLetzte 10 Kerzen Signale und Indikatoren:")
logger.info(data[['open', 'high', 'low', 'close', 'atr', 'x_atr_trailing_stop', 'buy_signal', 'sell_signal']].tail(10).to_string())


# #############################################################################
# #################### START: VERBESSERTE SIGNALLOGIK #########################
# #############################################################################

# Wir prüfen nur die letzte, vollständig geschlossene Kerze (Index -2) auf ein Signal.
# Das verhindert verspätete Einstiege durch alte Signale.
last_closed_candle = data.iloc[-2]

buy_signal = last_closed_candle['buy_signal']
sell_signal = last_closed_candle['sell_signal']

logger.info(f"Signalprüfung auf letzter Kerze ({last_closed_candle.name}): Buy={buy_signal}, Sell={sell_signal}")

# --- OFFENE POSITIONEN PRÜFEN ---
def fetch_positions():
    for attempt in range(params['max_retries']):
        try: return bitget.fetch_open_positions(params['symbol'])
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Positionen (Versuch {attempt+1}): {str(e)}")
            if attempt < params['max_retries'] - 1: time.sleep(params['retry_delay'])
    return []

positions = fetch_positions()
open_position = len(positions) > 0


# #############################################################################
# #################### START: FINALER HANDELS-LOGIKBLOCK ######################
# #############################################################################

# Status-Abgleich: Lokalen Tracker mit der Börse synchronisieren
if tracker_info['status'] == "in_trade" and not open_position:
    logger.warning(f"Tracker-Status war '{tracker_info['status']}', aber keine offene Position gefunden. Setze auf 'ok_to_trade' zurück.")
    send_telegram_message("ℹ️ *Status-Abgleich:* Keine offene Position gefunden. Bot ist wieder bereit zu handeln.")
    tracker_info = {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}
    update_tracker_file(tracker_file, tracker_info)


# Fall 1: Eine Position ist offen -> Verwalten oder bei Gegensignal schließen
if open_position:
    position_info = positions[0]
    position_side = position_info['side']
    
    # Position schließen, wenn ein Gegensignal vorliegt
    if (position_side == 'long' and sell_signal) or (position_side == 'short' and buy_signal):
        try:
            # --- WICHTIG: Zuerst den alten Stop-Loss stornieren ---
            sl_ids = tracker_info.get("stop_loss_ids", [])
            if sl_ids:
                logger.info(f"Storniere {len(sl_ids)} alte Stop-Loss-Order(s): {sl_ids}")
                for sl_id in sl_ids:
                    try:
                        bitget.cancel_trigger_order(sl_id, params['symbol'])
                    except Exception as sl_cancel_error:
                        logger.error(f"Konnte Stop-Loss-Order {sl_id} nicht stornieren: {sl_cancel_error}")
            
            # --- Dann die Position schließen ---
            current_price = data.iloc[-1]['close']
            bitget.flash_close_position(params['symbol'])
            
            log_trade_decision('SELL' if position_side == 'long' else 'BUY', 'POSITION_CLOSED_DUE_TO_OPPOSITE_SIGNAL', {'exit_price': current_price})
            logger.info(f"{position_side.upper()} Position bei {current_price} wegen Gegensignal geschlossen.")
            send_telegram_message(f"🚪 *Position geschlossen:* {position_side.upper()} bei {current_price:.2f} USDT aufgrund eines Gegensignals.")
            
            # --- Zuletzt den Tracker zurücksetzen ---
            update_tracker_file(tracker_file, {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []})
            
        except Exception as e:
            log_trade_decision('NONE', 'POSITION_CLOSE_ERROR', {'error': str(e)})
            logger.error(f"Fehler beim Schließen der Position: {str(e)}")
            send_telegram_message(f"❌ *Fehler beim Schließen der Position:* {str(e)}")
    
    # Nichts tun, wenn kein Gegensignal vorliegt
    else:
        logger.info(f"Offene {position_side}-Position wird gehalten. Kein Gegensignal gefunden.")
        log_trade_decision('NONE', 'HOLDING_POSITION', {'side': position_side, 'entryPrice': position_info.get('entryPrice')})

# Fall 2: Keine Position offen -> Prüfen, ob eine neue eröffnet werden soll
# HINWEIS: Dies ist ein `elif`. Wenn eine Position in diesem Durchlauf geschlossen wurde, wird hier nicht weitergemacht.
# Ändere `elif not open_position:` zu `else:` wenn du das "Stop-and-Reverse"-Verhalten möchtest.
elif not open_position:
    
    # Eine neue Position eröffnen, wenn ein gültiges Signal vorliegt
    if (buy_signal and params['use_longs']) or (sell_signal and params['use_shorts']):
        balance_info = fetch_balance()
        balance = balance_info.get('USDT', {}).get('total', 0.0)
        trade_size_usdt = (balance * (params['trade_size_pct'] / 100)) * params['leverage']
        min_trade_cost = 5.0

        if trade_size_usdt < min_trade_cost:
            logger.error(f"Handelsgröße ({trade_size_usdt:.2f} USDT) liegt unter dem Minimum ({min_trade_cost:.2f} USDT).")
            log_trade_decision('NONE', 'INSUFFICIENT_FUNDS', {'trade_size': trade_size_usdt, 'min_cost': min_trade_cost})
            send_telegram_message(f"❌ *Handel fehlgeschlagen:* Handelsgröße ({trade_size_usdt:.2f} USDT) zu gering.")
        else:
            side = 'buy' if buy_signal else 'sell'
            position_type = 'Long' if side == 'buy' else 'Short'
            try:
                current_price = data.iloc[-1]['close']
                amount_to_trade = trade_size_usdt / current_price
                
                # --- Position eröffnen ---
                bitget.place_market_order(params['symbol'], side, amount_to_trade)
                
                # --- Neuen Stop-Loss platzieren ---
                stop_loss_price = None
                if params['enable_stop_loss']:
                    stop_loss_price = current_price * (1 - params['stop_loss_pct']) if side == 'buy' else current_price * (1 + params['stop_loss_pct'])
                    sl_order = bitget.place_trigger_market_order(params['symbol'], 'sell' if side == 'buy' else 'buy', amount_to_trade, stop_loss_price, reduce=True)
                    update_tracker_file(tracker_file, {"status": "in_trade", "last_side": side, "stop_loss_ids": [sl_order['id']] if sl_order else []})
                    logger.info(f"Stop-Loss für {position_type}-Position gesetzt bei {stop_loss_price:.2f}")
                else:
                    update_tracker_file(tracker_file, {"status": "in_trade", "last_side": side, "stop_loss_ids": []})

                log_trade_decision(side.upper(), 'POSITION_OPENED', {'price': current_price, 'stop_loss': stop_loss_price})
                logger.info(f"{position_type}-Position bei {current_price} eröffnet.")
                
                sl_text = f"{stop_loss_price:.2f}" if stop_loss_price is not None else "N/A"
                telegram_msg = f"✅ *{position_type}-Position eröffnet:* bei {current_price:.2f} USDT\nStop-Loss bei {sl_text}"
                send_telegram_message(telegram_msg)
            
            except Exception as e:
                log_trade_decision(side.upper(), 'POSITION_OPEN_ERROR', {'error': str(e)})
                logger.error(f"Fehler beim Eröffnen der {position_type}-Position: {str(e)}")
                send_telegram_message(f"❌ *Fehler {position_type}-Position:* {str(e)}")

    # Nichts tun, wenn kein Signal vorliegt
    else:
        logger.info("Keine offene Position und kein neues Handelssignal gefunden.")
        log_trade_decision('NONE', 'NO_VALID_SIGNAL', {})


logger.info(f"<<< Ausführung abgeschlossen um {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
