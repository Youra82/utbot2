# utbot2/main.py (Version 3.6 - Integriert JaegerBot Order Management)
import os, sys, json, logging, pandas as pd, traceback, time
import google.generativeai as genai
import pandas_ta as ta
import toml
from google.api_core import exceptions
from logging.handlers import RotatingFileHandler # Für besseres Logging

# Korrekte Importpfade für utils
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT) # Fügt das Hauptverzeichnis hinzu

from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message
from utils.guardian import guardian_decorator # Importiere den Guardian

# --- Logging Setup (von JaegerBot inspiriert) ---
log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)

def setup_logging(symbol, timeframe):
    """ Richtet einen spezifischen Logger für jede Strategie ein. """
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_file = os.path.join(log_dir, f'utbot2_{safe_filename}.log')

    logger = logging.getLogger(f'utbot2_{safe_filename}')
    logger.setLevel(logging.INFO)
    logger.propagate = False # Verhindert doppelte Logs im Root-Logger

    # Nur Handler hinzufügen, wenn noch keine existieren
    if not logger.handlers:
        # File Handler ( rotiert bei 5MB, behält 3 Backups)
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        fh_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh_formatter.converter = time.gmtime # UTC Zeit im Log
        fh.setFormatter(fh_formatter)
        logger.addHandler(fh)

        # Console Handler (zeigt nur die Nachricht)
        ch = logging.StreamHandler()
        ch_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s: [%(name)s] %(message)s', datefmt='%H:%M:%S')
        ch_formatter.converter = time.gmtime # UTC Zeit im Log
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)

    return logger

# --- Globale Konfiguration ---
PROMPT_TEMPLATES = {
    "swing": "Swing-Trading-Strategie",
    "daytrade": "Day-Trading-Strategie",
    "scalp": "Scalping-Strategie"
}

# --- Hilfsfunktionen (unverändert) ---
def load_config(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
             # Unterscheide zwischen .toml und .json
             if file_path.endswith('.toml'):
                 return toml.load(f)
             elif file_path.endswith('.json'):
                 return json.load(f)
             else:
                 raise ValueError(f"Unbekanntes Konfigurationsformat: {file_path}")
    except FileNotFoundError:
        logging.error(f"FATAL: Konfigurationsdatei nicht gefunden: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"FATAL: Fehler beim Laden der Konfigurationsdatei {file_path}: {e}")
        sys.exit(1)


def calculate_candle_limit(timeframe, lookback_days):
    try:
        if 'm' in timeframe:
             minutes = int(timeframe.replace('m', ''))
             return int((60 / minutes) * 24 * lookback_days)
        elif 'h' in timeframe:
             hours = int(timeframe.replace('h', ''))
             return int((24 / hours) * lookback_days)
        elif 'd' in timeframe:
             days = int(timeframe.replace('d', ''))
             return int(lookback_days / days)
        else:
             logger.warning(f"Unbekanntes Timeframe-Format: {timeframe}. Verwende Fallback-Limit 1000.")
             return 1000
    except ValueError:
        logger.error(f"Ungültiges Timeframe-Format: {timeframe}. Verwende Fallback-Limit 1000.")
        return 1000

# --- Kernlogik: Trade-Eröffnung (leicht angepasst) ---
def attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_api, total_usdt_balance, logger):
    """ Versucht, basierend auf KI-Analyse einen neuen Trade zu eröffnen. """
    symbol, risk_cfg, timeframe = target['symbol'], target['risk'], target['timeframe']
    trading_style_text = PROMPT_TEMPLATES.get(strategy_cfg.get('trading_mode', 'swing'))
    margin_mode = risk_cfg.get('margin_mode', 'isolated') # Hole Margin Mode

    limit = calculate_candle_limit(timeframe, strategy_cfg['lookback_period_days'])
    logger.info(f"Lade {limit} Kerzen für {symbol} ({timeframe})...")
    ohlcv_df = exchange.fetch_ohlcv(symbol, timeframe, limit=limit) # Verwende limit statt since
    if ohlcv_df.empty or len(ohlcv_df) < 60: # Brauchen mind. 60 für die Analyse
        logger.error(f"Nicht genügend Kerzendaten erhalten (benötigt >= 60, erhalten {len(ohlcv_df)}). Überspringe.")
        return

    # 1. Indikatoren berechnen
    try:
        ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True)
        ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
        # Zusätzliche Indikatoren hinzufügen?
        # ohlcv_df.ta.rsi(append=True)
        # ohlcv_df.ta.mfi(append=True)
        ohlcv_df.dropna(inplace=True) # Wichtig: Erst nach allen Indikatoren droppen
    except Exception as e:
        logger.error(f"Fehler bei der Indikatorberechnung: {e}", exc_info=True)
        return

    # 2. Letzte 60 Kerzen für den Kontext vorbereiten
    data_to_send = ohlcv_df.tail(60)
    if len(data_to_send) < 60:
        logger.error(f"Nicht genügend Daten nach Indikatorberechnung (nur {len(data_to_send)} Kerzen).")
        return

    # Runden, um Token zu sparen. Wähle nur relevante Spalten aus.
    cols_to_send = ['open', 'high', 'low', 'close', 'volume'] + [col for col in data_to_send.columns if col not in ['open', 'high', 'low', 'close', 'volume', 'timestamp']]
    historical_data_string = data_to_send[cols_to_send].round(5).to_csv(index=False, line_terminator='\n')

    # 3. Aktuellen Preis holen
    latest = data_to_send.iloc[-1]; current_price = latest['close']

    # Info-Log (nur letzte Kerze) - BBP Spalte finden
    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name:
         indicator_summary = f"P={current_price:.4f}, StochK={latest['STOCHRSIk_14_14_3_3']:.1f}, StochD={latest['STOCHRSId_14_14_3_3']:.1f}, MACD_H={latest['MACDh_12_26_9']:.4f}, BBP={latest[bbp_column_name]:.2f}, OBV={latest['OBV']:.0f}"
    else:
         indicator_summary = f"P={current_price:.4f}, StochK={latest['STOCHRSIk_14_14_3_3']:.1f}, StochD={latest['STOCHRSId_14_14_3_3']:.1f}, MACD_H={latest['MACDh_12_26_9']:.4f}, OBV={latest['OBV']:.0f} (BBP Fehler)"
    logger.info(f"Aktuelle Indikatoren (letzte Kerze): {indicator_summary}")

    # 4. Gemini-Prompt mit 60-Kerzen-Kontext
    prompt = (
        "Du bist eine API, die NUR JSON zurückgibt. "
        "Analysiere die folgenden historischen Kerzendaten (CSV), um Trend, Momentum und Muster zu erkennen. "
        "Deine Antwort MUSS exakt diesem Format entsprechen: "
        "'{\"aktion\": \"KAUFEN|VERKAUFEN|HALTEN\", \"stop_loss\": zahl, \"take_profit\": zahl}'\n\n"
        f"Input: strategie='{trading_style_text}', symbol='{symbol}', aktueller_preis='{current_price}'.\n\n"
        "HISTORISCHE DATEN (letzte 60 Kerzen):\n"
        f"{historical_data_string}"
    )

    # 5. API-Aufruf mit Gemini
    try:
        logger.info("Sende Anfrage an Gemini...")
        # Timeout hinzufügen
        generation_config = genai.types.GenerationConfig(temperature=0.7) # Optional: Kreativität anpassen
        safety_settings = [ # Optional: Safety-Filter lockern (vorsichtig verwenden!)
             { "category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE" },
             { "category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE" },
             { "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE" },
             { "category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
        response = gemini_model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        logger.info("Antwort von Gemini erhalten.")

    except exceptions.ResourceExhausted as e:
        logger.warning(f"Gemini API-Ratenlimit erreicht. Pausiere 60s. Fehler: {e}")
        time.sleep(60)
        return
    except Exception as e:
        logger.error(f"Kritischer Fehler bei Gemini API-Anfrage: {e}", exc_info=True)
        return

    if not response.parts:
        try:
             # Versuche, Details aus 'prompt_feedback' zu loggen
             feedback = response.prompt_feedback
             logger.warning(f"Leere Antwort von Gemini (Blockiert durch Filter?). Feedback: {feedback}")
        except Exception:
             logger.warning(f"Leere Antwort von Gemini (Grund unbekannt).")
        return

    # 6. Antwortverarbeitung
    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    try:
        decision = json.loads(cleaned_response_text)
        logger.info(f"KI-Entscheidung: {decision}")
    except json.JSONDecodeError:
        logger.error(f"Antwort konnte nicht als JSON dekodiert werden: '{cleaned_response_text}'")
        return

    # 7. Risikomanagement und Order-Platzierung
    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        side = 'buy' if decision['aktion'] == 'KAUFEN' else 'sell'
        sl_price = decision.get('stop_loss')
        tp_price = decision.get('take_profit')

        # Validierung der SL/TP Preise
        if not isinstance(sl_price, (int, float)) or not isinstance(tp_price, (int, float)):
            logger.error(f"Ungültige SL/TP-Werte von KI: SL={sl_price}, TP={tp_price}")
            return
        if side == 'buy' and (sl_price >= current_price or tp_price <= current_price):
             logger.error(f"Logikfehler bei BUY: SL ({sl_price}) muss < Preis ({current_price}) < TP ({tp_price}) sein.")
             return
        if side == 'sell' and (sl_price <= current_price or tp_price >= current_price):
             logger.error(f"Logikfehler bei SELL: TP ({tp_price}) muss < Preis ({current_price}) < SL ({sl_price}) sein.")
             return

        # Risikoberechnung (wie vorher)
        allocated_capital = total_usdt_balance * (risk_cfg['portfolio_fraction_pct'] / 100)
        capital_at_risk = allocated_capital * (risk_cfg['risk_per_trade_pct'] / 100)
        sl_distance_pct = abs(current_price - sl_price) / current_price
        if sl_distance_pct < 0.001: # Verhindere Division durch ~Null (0.1% Mindestabstand)
            logger.error(f"Stop-Loss zu nah am Preis (Distanz < 0.1%). SL={sl_price}, Preis={current_price}. Trade abgebrochen.")
            return

        position_size_usdt = capital_at_risk / sl_distance_pct
        max_leverage = risk_cfg.get('max_leverage', 1) # Standard 1x Hebel
        final_leverage = round(max(1, min(position_size_usdt / allocated_capital, max_leverage)))
        amount_in_asset = position_size_usdt / current_price

        # Prüfung der Mindestmengen (wie vorher)
        try:
            market_info = exchange.session.market(symbol)
            min_amount = market_info['limits']['amount']['min']
            min_cost = market_info['limits']['cost']['min']

            if amount_in_asset < min_amount:
                logger.warning(f"Berechnete Menge ({amount_in_asset:.4f}) unter Minimum ({min_amount}). Trade abgebrochen.")
                return
            if position_size_usdt < min_cost:
                logger.warning(f"Berechneter Wert ({position_size_usdt:.2f} USDT) unter Minimum ({min_cost} USDT). Trade abgebrochen.")
                return
        except Exception as e:
            logger.error(f"Fehler beim Prüfen der Marktlimits: {e}. Breche Trade vorsichtshalber ab.")
            return

        # Trade ausführen
        try:
            logger.info(f"Versuche Trade: {side} {amount_in_asset:.4f} {symbol.split('/')[0]} ({position_size_usdt:.2f} USDT) mit {final_leverage}x Hebel...")
            exchange.set_leverage(symbol, final_leverage, margin_mode)

            # Verwende die ROBUSTE Order-Funktion
            order_result = exchange.create_market_order_with_sl_tp(symbol, side, amount_in_asset, sl_price, tp_price, margin_mode)

            # Extrahiere tatsächlichen Einstiegspreis aus dem Ergebnis
            actual_entry_price = order_result.get('average') or entry_price # 'average' ist oft der gefüllte Preis
            filled_amount = order_result.get('filled') or amount_in_asset

            logger.info(f"✅ Trade erfolgreich platziert! OrderID: {order_result['id']}, Entry: ≈{actual_entry_price:.4f}, Menge: {filled_amount:.4f}")

            msg = (f"🚀 NEUER TRADE: *{symbol}*\n\n"
                   f"Modus: *{strategy_cfg['trading_mode'].capitalize()}*\n"
                   f"Aktion: *{decision['aktion']}* (Dyn. Hebel: *{final_leverage}x*)\n"
                   f"Größe: {filled_amount * actual_entry_price:.2f} USDT\n" # Verwende tatsächliche Werte
                   f"Entry: ≈ {actual_entry_price:.4f}\n"
                   f"Stop-Loss: {sl_price}\n"
                   f"Take-Profit: {tp_price}")
            send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)

        except Exception as e:
            logger.error(f"❌ FEHLER BEI TRADE-AUSFÜHRUNG: {e}", exc_info=True)
            # WICHTIG: Housekeeping nach fehlgeschlagenem Trade versuchen!
            logger.info("Versuche Housekeeping nach fehlgeschlagener Order...")
            exchange.cleanup_all_open_orders(symbol)

    else:
        logger.info(f"Keine Handelsaktion ({decision.get('aktion', 'unbekannt')}).")


# --- Hauptfunktion (Überarbeitet mit JaegerBot-Logik) ---
@guardian_decorator # Füge den Guardian hinzu
def run_strategy_cycle(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, logger):
    """ Führt einen kompletten Prüf- und Handelszyklus für EINE Strategie aus. """
    symbol = target['symbol']
    logger.info(f"--- Starte Zyklus für {symbol} ({target['timeframe']}) ---")

    try:
        # 1. Prüfe auf offene Positionen für DIESES Symbol
        position = exchange.fetch_open_positions(symbol)
        position = position[0] if position else None # Nimm die erste (sollte nur eine sein)

        if position:
            # Position existiert - Loggen und nichts tun (SL/TP sind aktiv)
            entry_price = float(position.get('entryPrice', 0))
            contracts = float(position.get('contracts', 0))
            side = position.get('side', 'unbekannt')
            logger.info(f"Offene Position gefunden: {side} {contracts} @ {entry_price:.4f}. Warte auf SL/TP.")
        else:
            # Keine Position offen - Housekeeping und dann nach neuem Signal suchen
            logger.info("Keine offene Position gefunden.")

            # 2. Housekeeper: Storniere alle alten/verwaisten Orders für dieses Symbol
            logger.info("Starte Housekeeping (storniere alte Orders)...")
            exchange.cleanup_all_open_orders(symbol)
            logger.info("Housekeeping abgeschlossen.")

            # 3. Suche nach neuem Trade-Signal und eröffne ggf. Position
            attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, logger)

    except ccxt.RateLimitExceeded as e:
         logger.warning(f"Exchange Rate Limit erreicht: {e}. Pausiere 30s.")
         time.sleep(30)
    except ccxt.NetworkError as e:
         logger.warning(f"Netzwerkfehler zur Exchange: {e}. Pausiere 15s.")
         time.sleep(15)
    # except Exception as e: # Wird jetzt vom Guardian gefangen
    #      logger.error(f"Unerwarteter Fehler im Strategie-Zyklus für {symbol}: {e}", exc_info=True)
    #      # Sende Telegram-Nachricht im Fehlerfall? Der Guardian macht das jetzt.
    #      # send_telegram_message(telegram_config['bot_token'], telegram_config['chat_id'], f"🚨 FEHLER bei *{symbol}*!\n\n`{str(e)}`")

    logger.info(f"--- Zyklus für {symbol} abgeschlossen ---")


def main():
    # Setup Root-Logger (nur für globale Meldungen und Fehler beim Start)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler()])
    logging.Formatter.converter = time.gmtime # UTC Zeit
    root_logger = logging.getLogger() # Kein spezifischer Name, fängt alles auf, was nicht von Strategie-Loggern behandelt wird

    root_logger.info("==============================================")
    root_logger.info("=  utbot2 v3.6 (JaegerBot Order Mgmt)  =")
    root_logger.info("==============================================")

    # --- Lade Konfigurationen ---
    try:
        config = load_config('config.toml')
        secrets = load_config('secret.json')
    except Exception:
         # Fehler wurden bereits in load_config geloggt, hier nur beenden
         return

    # --- Initialisiere Gemini ---
    try:
        genai.configure(api_key=secrets['google']['api_key'])
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        root_logger.info("Gemini-Client erfolgreich initialisiert.")
    except KeyError:
        root_logger.critical("FATAL: 'google' oder 'api_key' nicht in secret.json gefunden!")
        return
    except Exception as e:
        root_logger.critical(f"FATAL: Fehler beim Initialisieren des Gemini-Clients: {e}")
        return

    # --- Initialisiere Exchange ---
    try:
        exchange = ExchangeHandler(secrets['bitget'])
        root_logger.info("ExchangeHandler erfolgreich initialisiert.")
    except KeyError:
         root_logger.critical("FATAL: 'bitget' Sektion nicht in secret.json gefunden!")
         return
    except Exception as e:
         root_logger.critical(f"FATAL: Fehler beim Initialisieren des ExchangeHandlers: {e}", exc_info=True)
         return

    # --- Haupt-Schleife ---
    strategy_cfg = config['strategy']
    telegram_config = secrets['telegram']

    while True: # Endlos-Schleife
        root_logger.info("=== Starte neuen Handelszyklus ===")
        try:
            total_usdt_balance = exchange.fetch_balance_usdt()
            if total_usdt_balance <= 0:
                root_logger.error("Kontoguthaben ist 0 oder konnte nicht abgerufen werden. Pausiere 5 Minuten.")
                time.sleep(300) # 5 Minuten Pause
                continue # Nächster Zyklus

            root_logger.info(f"Aktuelles verfügbares Guthaben: {total_usdt_balance:.2f} USDT")

            active_targets = [t for t in config.get('targets', []) if t.get('enabled', False)]
            if not active_targets:
                 root_logger.warning("Keine aktiven Targets in config.toml gefunden. Pausiere 1 Minute.")
                 time.sleep(60)
                 continue

            for target in active_targets:
                symbol = target['symbol']
                timeframe = target['timeframe']
                strategy_logger = setup_logging(symbol, timeframe) # Hole/Erstelle den Logger für diese Strategie

                # Rufe den dekorierten Zyklus auf
                run_strategy_cycle(target, strategy_cfg, exchange, gemini_model, telegram_config, total_usdt_balance, strategy_logger)

                strategy_logger.info(f"Warte 20 Sekunden vor dem nächsten Coin...")
                time.sleep(20) # Pause zwischen Coins

        except Exception as e:
            # Fange unerwartete Fehler in der Hauptschleife ab
            root_logger.critical(f"FATALER FEHLER in der Hauptschleife: {e}", exc_info=True)
            try:
                 send_telegram_message(telegram_config['bot_token'], telegram_config['chat_id'], f"🚨 FATALER FEHLER in utbot2 Hauptschleife!\n\n`{str(e)}`\n\nBot wird versuchen neu zu starten nach 1 Minute.")
            except Exception as tel_e:
                 root_logger.error(f"Konnte keine Telegram-Nachricht über fatalen Fehler senden: {tel_e}")
            time.sleep(60) # Warte 1 Minute vor dem Neustart des Zyklus

        root_logger.info("=== Handelszyklus abgeschlossen. Warte 5 Minuten bis zum nächsten Lauf. ===")
        time.sleep(300) # 5 Minuten Pause zwischen den kompletten Zyklen


if __name__ == "__main__":
    main()
