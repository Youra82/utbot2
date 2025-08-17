# run.py (Final - mit allen Korrekturen und Flip-Logik)
import os
import sys
import json
import pandas as pd
import numpy as np
import ta
import time
import logging
import requests

# Pfad für Modulimporte
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from utilities.bitget_futures import BitgetFutures

# --- TELEGRAM-KONFIGURATION ---
telegram_bot_token = None
telegram_chat_id = None

# --- TELEGRAM-FUNKTION ---
def send_telegram_message(message):
    global telegram_bot_token, telegram_chat_id
    if not telegram_bot_token or not telegram_chat_id:
        logger.warning("Telegram-Daten in secret.json nicht gefunden.")
        return
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    payload = {'chat_id': telegram_chat_id, 'text': message, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        logger.info("Telegram-Nachricht erfolgreich gesendet.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Fehler beim Senden der Telegram-Nachricht: {e}")

# --- KONFIGURATION ---
params = {
    'symbol': 'BTC/USDT:USDT',
    'timeframe': '15m',
    'margin_mode': 'isolated',
    'leverage': 10,
    'use_longs': True,
    'use_shorts': True,
    'stop_loss_pct': 0.004,
    'enable_stop_loss': True,
    'ut_key_value': 1,
    'ut_atr_period': 10,
    'trade_size_pct': 25,
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.FileHandler(log_file), logging.StreamHandler()])
logger = logging.getLogger('envelope_bot')

# --- AUTHENTIFIZIERUNG ---
logger.info(f">>> starting execution for {params['symbol']}")
try:
    with open(key_path, "r") as f:
        secrets = json.load(f)
        api_setup = secrets[key_name]
        telegram_setup = secrets.get('telegram', {})
    telegram_bot_token = telegram_setup.get('bot_token')
    telegram_chat_id = telegram_setup.get('chat_id')
except Exception as e:
    logger.critical(f"Kritischer Fehler beim Laden der Keys: {e}")
    sys.exit(1)

def create_bitget_connection():
    for attempt in range(params['max_retries']):
        try:
            return BitgetFutures(api_setup)
        except Exception as e:
            logger.error(f"Verbindungsfehler (Versuch {attempt+1}/{params['max_retries']}): {e}")
            if attempt < params['max_retries'] - 1: time.sleep(params['retry_delay'])
    logger.critical("Kritischer Fehler: API-Verbindung fehlgeschlagen")
    send_telegram_message("❌ *Kritischer Fehler:* API-Verbindung zu Bitget fehlgeschlagen.")
    sys.exit(1)

bitget = create_bitget_connection()

# --- START-SETUP ---
try:
    bitget.set_margin_mode(params['symbol'], params['margin_mode'])
    bitget.set_leverage(params['symbol'], params['leverage'])
except Exception as e:
    if "margin mode cannot be adjusted" in str(e):
        logger.info("Margin-Modus/Hebel bereits durch offene Position festgelegt.")
    else:
        logger.error(f"Fehler bei Setup: {e}")

# --- TRACKER-HANDLING ---
def read_tracker_file(file_path):
    try:
        with open(file_path, 'r') as file: return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}

def update_tracker_file(file_path, data):
    with open(file_path, 'w') as file: json.dump(data, file)

tracker_info = read_tracker_file(tracker_file)

# --- STRATEGIE-LOGIK ---
def calculate_ut_signals(data, params):
    src = data['close']
    data['atr'] = ta.volatility.average_true_range(data['high'], data['low'], data['close'], window=params['ut_atr_period'])
    n_loss = params['ut_key_value'] * data['atr']
    x_atr_trailing_stop = np.zeros(len(data))
    for i in range(len(data)):
        if i == 0: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
        else:
            if src.iloc[i] > x_atr_trailing_stop[i-1] and src.iloc[i-1] > x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = max(x_atr_trailing_stop[i-1], src.iloc[i] - n_loss.iloc[i])
            elif src.iloc[i] < x_atr_trailing_stop[i-1] and src.iloc[i-1] < x_atr_trailing_stop[i-1]:
                x_atr_trailing_stop[i] = min(x_atr_trailing_stop[i-1], src.iloc[i] + n_loss.iloc[i])
            else:
                if src.iloc[i] > x_atr_trailing_stop[i-1]: x_atr_trailing_stop[i] = src.iloc[i] - n_loss.iloc[i]
                else: x_atr_trailing_stop[i] = src.iloc[i] + n_loss.iloc[i]
    data['x_atr_trailing_stop'] = x_atr_trailing_stop
    data['buy_signal'] = (src > data['x_atr_trailing_stop']) & (src.shift(1) <= data['x_atr_trailing_stop'].shift(1))
    data['sell_signal'] = (src < data['x_atr_trailing_stop']) & (src.shift(1) >= data['x_atr_trailing_stop'].shift(1))
    return data

# --- NEUE FUNKTION ---
# Refaktoriert: Die Logik zum Eröffnen einer Position wurde in eine eigene Funktion ausgelagert,
# um Code-Wiederholung zu vermeiden.
def open_new_position(side):
    """ Eröffnet eine neue Position basierend auf der übergebenen 'side' ('buy' oder 'sell'). """
    try:
        balance_info = bitget.fetch_balance()
        balance = balance_info.get('USDT', {}).get('total', 0.0)
        trade_size_usdt = (balance * (params['trade_size_pct'] / 100)) * params['leverage']
        
        min_trade_cost = 5.0

        if trade_size_usdt >= min_trade_cost:
            position_type = 'Long' if side == 'buy' else 'Short'
            current_price = data.iloc[-1]['close']
            amount_to_trade = trade_size_usdt / current_price

            bitget.place_market_order(params['symbol'], side, amount_to_trade)

            stop_loss_price = None
            if params['enable_stop_loss']:
                sl_side = 'sell' if side == 'buy' else 'buy'
                stop_loss_price = current_price * (1 - params['stop_loss_pct']) if side == 'buy' else current_price * (1 + params['stop_loss_pct'])
                sl_order = bitget.place_trigger_market_order(params['symbol'], sl_side, amount_to_trade, stop_loss_price, reduce=True)

                stop_loss_id = None
                if sl_order:
                    if 'id' in sl_order and sl_order['id']: stop_loss_id = sl_order['id']
                    elif 'info' in sl_order and 'orderId' in sl_order['info']: stop_loss_id = sl_order['info']['orderId']

                if stop_loss_id:
                    logger.info(f"Successfully extracted Stop-Loss ID: {stop_loss_id}")
                    update_tracker_file(tracker_file, {"status": "in_trade", "last_side": side, "stop_loss_ids": [stop_loss_id]})
                else:
                    logger.error("KONNTE STOP-LOSS ID NICHT AUS DER API ANTWORT EXTRAHIEREN!")
                    update_tracker_file(tracker_file, {"status": "in_trade", "last_side": side, "stop_loss_ids": []})
            else:
                update_tracker_file(tracker_file, {"status": "in_trade", "last_side": side, "stop_loss_ids": []})

            sl_text_log = f"{stop_loss_price:.2f}" if stop_loss_price is not None else "N/A"
            logger.info(f"{position_type}-Position bei {current_price:.2f} eröffnet. Stop-Loss bei {sl_text_log}")

            sl_text_telegram = f"{stop_loss_price:.2f}" if stop_loss_price is not None else "N/A"
            send_telegram_message(f"✅ *{position_type}-Position eröffnet:* bei {current_price:.2f} USDT\nStop-Loss bei {sl_text_telegram}")
        else:
            logger.error(f"Handelsgröße ({trade_size_usdt:.2f} USDT) zu gering. Minimum ist ca. {min_trade_cost} USDT.")
    except Exception as e:
        logger.error(f"Fehler beim Eröffnen der {side}-Position: {e}")


# --- DATENLADEN ---
try:
    data = bitget.fetch_recent_ohlcv(params['symbol'], params['timeframe'], 100)
    data = calculate_ut_signals(data, params)
except Exception as e:
    logger.critical(f"Kritischer Fehler beim Laden der Daten: {e}")
    sys.exit(1)

# --- FINALE HANDELS-LOGIK ---
last_closed_candle = data.iloc[-2]
buy_signal = last_closed_candle['buy_signal']
sell_signal = last_closed_candle['sell_signal']

try:
    positions = bitget.fetch_open_positions(params['symbol'])
    open_position = len(positions) > 0
except Exception as e:
    logger.error(f"Fehler beim Abrufen der Positionen: {e}")
    sys.exit(1)

if tracker_info['status'] == "in_trade" and not open_position:
    logger.warning("Tracker-Status war 'in_trade', aber keine Position gefunden. Setze zurück.")
    tracker_info = {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []}
    update_tracker_file(tracker_file, tracker_info)

# --- ANGEPASSTE LOGIK ---
# Die Logik wurde überarbeitet, um einen sofortigen "Flip" der Position bei einem Gegensignal zu ermöglichen.
if open_position:
    position_info = positions[0]
    position_side = position_info['side']

    should_close_long = position_side == 'long' and sell_signal
    should_close_short = position_side == 'short' and buy_signal

    if should_close_long or should_close_short:
        try:
            # 1. Alte Stop-Loss-Order stornieren
            sl_ids = tracker_info.get("stop_loss_ids", [])
            if sl_ids:
                logger.info(f"Storniere {len(sl_ids)} alte Stop-Loss-Order(s): {sl_ids}")
                for sl_id in sl_ids:
                    try: bitget.cancel_trigger_order(sl_id, params['symbol'])
                    except Exception as sl_cancel_error: logger.error(f"Konnte SL-Order {sl_id} nicht stornieren: {sl_cancel_error}")
            
            # 2. Aktuelle Position schließen
            bitget.flash_close_position(params['symbol'])
            closed_side_msg = "LONG" if should_close_long else "SHORT"
            logger.info(f"{closed_side_msg} Position wegen Gegensignal geschlossen.")
            send_telegram_message(f"🚪 *Position geschlossen:* {closed_side_msg} aufgrund eines Gegensignals.")
            
            # 3. Sofort neue Position in die entgegengesetzte Richtung eröffnen ("Flip")
            if should_close_long and params['use_shorts']:
                logger.info("Gegensignal (SELL) erkannt. Eröffne sofort Short-Position.")
                open_new_position('sell')
            elif should_close_short and params['use_longs']:
                logger.info("Gegensignal (BUY) erkannt. Eröffne sofort Long-Position.")
                open_new_position('buy')
            else:
                # Falls die entgegengesetzte Richtung nicht erlaubt ist, Tracker zurücksetzen.
                update_tracker_file(tracker_file, {"status": "ok_to_trade", "last_side": None, "stop_loss_ids": []})

        except Exception as e:
            logger.error(f"Fehler beim Schließen/Flippen der Position: {e}")
    else:
        logger.info(f"Offene {position_side}-Position wird gehalten.")

elif not open_position:
    if buy_signal and params['use_longs']:
        open_new_position('buy')
    elif sell_signal and params['use_shorts']:
        open_new_position('sell')
    else:
        logger.info("Kein neues Handelssignal gefunden.")

logger.info(f"<<< Ausführung abgeschlossen")

