# utbot2/main.py (Version 3.7 - Crontab-fähig)
import os, sys, json, logging, pandas as pd, traceback, time, argparse # argparse hinzugefügt
import google.generativeai as genai
import pandas_ta as ta
import toml
from google.api_core import exceptions
from logging.handlers import RotatingFileHandler

# Korrekte Importpfade für utils
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# Stelle sicher, dass das übergeordnete Verzeichnis (utbot2/) im Pfad ist,
# damit utils gefunden wird, wenn main.py direkt ausgeführt wird.
sys.path.append(os.path.dirname(PROJECT_ROOT)) # Fügt das Verzeichnis über 'src' hinzu, falls es eine src-Struktur gäbe
# Wenn main.py im Hauptverzeichnis liegt, ist das hier eventuell nicht nötig, schadet aber nicht.
sys.path.append(PROJECT_ROOT)


from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message
from utils.guardian import guardian_decorator

# --- Logging Setup (unverändert) ---
log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)

def setup_logging(symbol, timeframe):
    """ Richtet einen spezifischen Logger für jede Strategie ein. """
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_file = os.path.join(log_dir, f'utbot2_{safe_filename}.log')

    logger = logging.getLogger(f'utbot2_{safe_filename}')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        fh_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh_formatter.converter = time.gmtime
        fh.setFormatter(fh_formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s: [%(name)s] %(message)s', datefmt='%H:%M:%S')
        ch_formatter.converter = time.gmtime
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)

    return logger

# --- Globale Konfiguration & Hilfsfunktionen (unverändert) ---
PROMPT_TEMPLATES = { "swing": "...", "daytrade": "...", "scalp": "..." } # Gekürzt zur Übersicht

def load_config(file_path):
    # ... (Code wie in Version 3.6) ...
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
             if file_path.endswith('.toml'): return toml.load(f)
             elif file_path.endswith('.json'): return json.load(f)
             else: raise ValueError(f"Unbekanntes Konfigurationsformat: {file_path}")
    except FileNotFoundError:
        # Verwende den Root-Logger für kritische Startfehler
        logging.getLogger().critical(f"FATAL: Konfigurationsdatei nicht gefunden: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.getLogger().critical(f"FATAL: Fehler beim Laden der Konfigurationsdatei {file_path}: {e}")
        sys.exit(1)


def calculate_candle_limit(timeframe, lookback_days, logger): # Logger hinzugefügt
    # ... (Code wie in Version 3.6, verwendet jetzt den übergebenen Logger) ...
    try:
        if 'm' in timeframe:
             minutes = int(timeframe.replace('m', ''))
             if minutes == 0: raise ValueError("Minuten dürfen nicht 0 sein")
             return int((60 / minutes) * 24 * lookback_days)
        elif 'h' in timeframe:
             hours = int(timeframe.replace('h', ''))
             if hours == 0: raise ValueError("Stunden dürfen nicht 0 sein")
             return int((24 / hours) * lookback_days)
        elif 'd' in timeframe:
             days = int(timeframe.replace('d', ''))
             if days == 0: raise ValueError("Tage dürfen nicht 0 sein")
             return int(lookback_days / days)
        else:
             logger.warning(f"Unbekanntes Timeframe-Format: {timeframe}. Verwende Fallback-Limit 1000.")
             return 1000
    except ValueError as e:
        logger.error(f"Ungültiges Timeframe-Format '{timeframe}': {e}. Verwende Fallback-Limit 1000.")
        return 1000
    except ZeroDivisionError:
         logger.error(f"Ungültiger Timeframe führt zu Division durch Null: {timeframe}. Verwende Fallback-Limit 1000.")
         return 1000

# --- Trade-Eröffnung (unverändert gegenüber v3.6) ---
def attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_api, total_usdt_balance, logger):
    # ... (Kompletter Code aus Version 3.6 hier einfügen) ...
    symbol, risk_cfg, timeframe = target['symbol'], target['risk'], target['timeframe']
    trading_style_text = PROMPT_TEMPLATES.get(strategy_cfg.get('trading_mode', 'swing'))
    margin_mode = risk_cfg.get('margin_mode', 'isolated')

    limit = calculate_candle_limit(timeframe, strategy_cfg['lookback_period_days'], logger)
    logger.info(f"Lade {limit} Kerzen für {symbol} ({timeframe})...")
    ohlcv_df = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    if ohlcv_df.empty or len(ohlcv_df) < 60:
        logger.error(f"Nicht genügend Kerzendaten erhalten (benötigt >= 60, erhalten {len(ohlcv_df)}). Überspringe.")
        return

    try:
        ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True)
        ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
        ohlcv_df.dropna(inplace=True)
    except Exception as e:
        logger.error(f"Fehler bei der Indikatorberechnung: {e}", exc_info=True)
        return

    data_to_send = ohlcv_df.tail(60)
    if len(data_to_send) < 60:
        logger.error(f"Nicht genügend Daten nach Indikatorberechnung (nur {len(data_to_send)} Kerzen).")
        return

    cols_to_send = ['open', 'high', 'low', 'close', 'volume'] + [col for col in data_to_send.columns if col not in ['open', 'high', 'low', 'close', 'volume', 'timestamp']]
    historical_data_string = data_to_send[cols_to_send].round(5).to_csv(index=False, line_terminator='\n')

    latest = data_to_send.iloc[-1]; current_price = latest['close']

    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name:
         indicator_summary = f"P={current_price:.4f}, StochK={latest['STOCHRSIk_14_14_3_3']:.1f}, StochD={latest['STOCHRSId_14_14_3_3']:.1f}, MACD_H={latest['MACDh_12_26_9']:.4f}, BBP={latest[bbp_column_name]:.2f}, OBV={latest['OBV']:.0f}"
    else:
         indicator_summary = f"P={current_price:.4f}, StochK={latest['STOCHRSIk_14_14_3_3']:.1f}, StochD={latest['STOCHRSId_14_14_3_3']:.1f}, MACD_H={latest['MACDh_12_26_9']:.4f}, OBV={latest['OBV']:.0f} (BBP Fehler)"
    logger.info(f"Aktuelle Indikatoren (letzte Kerze): {indicator_summary}")

    prompt = (
        "Du bist eine API, die NUR JSON zurückgibt..." # Gekürzt, prompt bleibt gleich
        f"Input: strategie='{trading_style_text}', symbol='{symbol}', aktueller_preis='{current_price}'.\n\n"
        "HISTORISCHE DATEN (letzte 60 Kerzen):\n"
        f"{historical_data_string}"
    )

    try:
        logger.info("Sende Anfrage an Gemini...")
        generation_config = genai.types.GenerationConfig(temperature=0.7)
        safety_settings = [ { "category": c, "threshold": "BLOCK_NONE" } for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
        response = gemini_model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        logger.info("Antwort von Gemini erhalten.")

    except exceptions.ResourceExhausted as e: logger.warning(f"Gemini API-Ratenlimit erreicht. Pausiere 60s. Fehler: {e}"); time.sleep(60); return
    except Exception as e: logger.error(f"Kritischer Fehler bei Gemini API-Anfrage: {e}", exc_info=True); return

    if not response.parts:
        try: feedback = response.prompt_feedback; logger.warning(f"Leere Antwort von Gemini (Blockiert?). Feedback: {feedback}")
        except Exception: logger.warning(f"Leere Antwort von Gemini (Grund unbekannt).")
        return

    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    try: decision = json.loads(cleaned_response_text); logger.info(f"KI-Entscheidung: {decision}")
    except json.JSONDecodeError: logger.error(f"Antwort nicht JSON: '{cleaned_response_text}'"); return

    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        side = 'buy' if decision['aktion'] == 'KAUFEN' else 'sell'
        sl_price = decision.get('stop_loss')
        tp_price = decision.get('take_profit')

        if not isinstance(sl_price, (int, float)) or not isinstance(tp_price, (int, float)): logger.error(f"Ungültige SL/TP: SL={sl_price}, TP={tp_price}"); return
        if side == 'buy' and (sl_price >= current_price or tp_price <= current_price): logger.error(f"Logikfehler BUY: SL({sl_price}) < P({current_price}) < TP({tp_price}) nicht erfüllt."); return
        if side == 'sell' and (sl_price <= current_price or tp_price >= current_price): logger.error(f"Logikfehler SELL: TP({tp_price}) < P({current_price}) < SL({sl_price}) nicht erfüllt."); return

        allocated_capital = total_usdt_balance * (risk_cfg['portfolio_fraction_pct'] / 100)
        capital_at_risk = allocated_capital * (risk_cfg['risk_per_trade_pct'] / 100)
        sl_distance_pct = abs(current_price - sl_price) / current_price
        if sl_distance_pct < 0.001: logger.error(f"SL zu nah (<0.1%). SL={sl_price}, P={current_price}. Abbruch."); return

        position_size_usdt = capital_at_risk / sl_distance_pct
        max_leverage = risk_cfg.get('max_leverage', 1)
        final_leverage = round(max(1, min(position_size_usdt / allocated_capital, max_leverage)))
        amount_in_asset = position_size_usdt / current_price

        try:
            market_info = exchange.session.market(symbol)
            min_amount = market_info['limits']['amount']['min']
            min_cost = market_info['limits']['cost']['min']
            if amount_in_asset < min_amount: logger.warning(f"Menge {amount_in_asset:.4f} < Min {min_amount}. Abbruch."); return
            if position_size_usdt < min_cost: logger.warning(f"Wert {position_size_usdt:.2f} < Min {min_cost}. Abbruch."); return
        except Exception as e: logger.error(f"Fehler bei Marktlimits: {e}. Abbruch."); return

        try:
            logger.info(f"Versuche Trade: {side} {amount_in_asset:.4f} {symbol.split('/')[0]} ({position_size_usdt:.2f} USDT) mit {final_leverage}x Hebel...")
            exchange.set_leverage(symbol, final_leverage, margin_mode)
            order_result = exchange.create_market_order_with_sl_tp(symbol, side, amount_in_asset, sl_price, tp_price, margin_mode)
            actual_entry_price = order_result.get('average') or current_price
            filled_amount = order_result.get('filled') or amount_in_asset
            logger.info(f"✅ Trade platziert! ID: {order_result['id']}, Entry: ≈{actual_entry_price:.4f}, Menge: {filled_amount:.4f}")
            msg = (f"🚀 NEUER TRADE: *{symbol}*...\n" # Gekürzt
                   f"Aktion: *{decision['aktion']}* ({final_leverage}x)\n"
                   f"Größe: {filled_amount * actual_entry_price:.2f} USDT\nEntry: ≈ {actual_entry_price:.4f}\nSL: {sl_price}\nTP: {tp_price}")
            send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)
        except Exception as e:
            logger.error(f"❌ FEHLER BEI TRADE-AUSFÜHRUNG: {e}", exc_info=True)
            logger.info("Versuche Housekeeping...")
            exchange.cleanup_all_open_orders(symbol)
    else: logger.info(f"Keine Handelsaktion ({decision.get('aktion', 'unbekannt')}).")


# --- Strategie-Zyklus (unverändert gegenüber v3.6) ---
@guardian_decorator
def run_strategy_cycle(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, logger):
    """ Führt einen kompletten Prüf- und Handelszyklus für EINE Strategie aus. """
    # ... (Kompletter Code aus Version 3.6 hier einfügen) ...
    symbol = target['symbol']
    logger.info(f"--- Starte Zyklus für {symbol} ({target['timeframe']}) ---")
    try:
        position = exchange.fetch_open_positions(symbol)
        position = position[0] if position else None
        if position:
            entry_price = float(position.get('entryPrice', 0)); contracts = float(position.get('contracts', 0)); side = position.get('side', 'unbekannt')
            logger.info(f"Offene Position: {side} {contracts} @ {entry_price:.4f}. Warte auf SL/TP.")
        else:
            logger.info("Keine offene Position gefunden.")
            logger.info("Starte Housekeeping (storniere alte Orders)...")
            exchange.cleanup_all_open_orders(symbol)
            logger.info("Housekeeping abgeschlossen.")
            attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, logger)
    except ccxt.RateLimitExceeded as e: logger.warning(f"Exchange Rate Limit: {e}. Pausiere 30s."); time.sleep(30)
    except ccxt.NetworkError as e: logger.warning(f"Netzwerkfehler: {e}. Pausiere 15s."); time.sleep(15)
    # Allgemeine Exceptions werden vom Guardian gefangen
    logger.info(f"--- Zyklus für {symbol} abgeschlossen ---")


# --- NEUE Hauptfunktion (wird vom Master Runner aufgerufen) ---
def main():
    # --- Argumente parsen ---
    parser = argparse.ArgumentParser(description="utbot2 Einzelstrategie-Runner")
    parser.add_argument('--symbol', required=True, help="Das Handelspaar (z.B. BTC/USDT:USDT)")
    parser.add_argument('--timeframe', required=True, help="Das Zeitfenster (z.B. 1h)")
    args = parser.parse_args()

    # --- Logger für diese spezifische Strategie einrichten ---
    logger = setup_logging(args.symbol, args.timeframe)
    logger.info("==============================================")
    logger.info(f"=  Starte utbot2 v3.7 für {args.symbol} ({args.timeframe}) =")
    logger.info("==============================================")

    # --- Lade Konfigurationen ---
    try:
        config = load_config('config.toml')
        secrets = load_config('secret.json')
    except Exception as e:
        logger.critical(f"Konnte Konfiguration nicht laden: {e}", exc_info=True)
        return # Beendet diesen Prozess

    # --- Finde das spezifische Target ---
    target = None
    for t in config.get('targets', []):
        if t.get('symbol') == args.symbol and t.get('timeframe') == args.timeframe and t.get('enabled', False):
            target = t
            break

    if not target:
        logger.error(f"Kein aktives Target für {args.symbol} ({args.timeframe}) in config.toml gefunden.")
        return

    # --- Initialisiere Gemini ---
    try:
        genai.configure(api_key=secrets['google']['api_key'])
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini-Client initialisiert.")
    except KeyError: logger.critical("FATAL: Google API Key nicht in secret.json!"); return
    except Exception as e: logger.critical(f"FATAL: Gemini Init Fehler: {e}"); return

    # --- Initialisiere Exchange ---
    try:
        exchange = ExchangeHandler(secrets['bitget'])
        logger.info("ExchangeHandler initialisiert.")
    except KeyError: logger.critical("FATAL: Bitget Keys nicht in secret.json!"); return
    except Exception as e: logger.critical(f"FATAL: Exchange Init Fehler: {e}", exc_info=True); return

    # --- Führe den Strategie-Zyklus EINMAL aus ---
    try:
        total_usdt_balance = exchange.fetch_balance_usdt()
        if total_usdt_balance <= 0:
            logger.error("Kontoguthaben ist 0 oder konnte nicht abgerufen werden. Überspringe diesen Lauf.")
            return

        logger.info(f"Verfügbares Guthaben: {total_usdt_balance:.2f} USDT")
        strategy_cfg = config['strategy']
        telegram_config = secrets['telegram']

        # Rufe den dekorierten Zyklus auf
        run_strategy_cycle(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, logger)

    except Exception as e:
        # Fange unerwartete Fehler im Hauptteil ab (sollte eigentlich der Guardian tun)
        logger.critical(f"FATALER FEHLER im Hauptprozess für {args.symbol}: {e}", exc_info=True)
        try:
             send_telegram_message(telegram_config['bot_token'], telegram_config['chat_id'], f"🚨 FATALER FEHLER in utbot2 ({args.symbol})!\n\n`{str(e)}`")
        except Exception: pass # Ignoriere Fehler beim Senden

    logger.info(f">>> Lauf für {args.symbol} ({args.timeframe}) abgeschlossen <<<")

if __name__ == "__main__":
    main()
