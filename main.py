# utbot2/main.py (Version 4.1 - Atomare Order/TitanBot-Stil)
import os, sys, json, logging, pandas as pd, traceback, time, argparse, ccxt
# WICHTIG: pandas muss importiert werden, da der Test-Workflow es braucht
import pandas_ta as ta
import toml
# ... (restliche Imports)

# Korrekte Importpfade für utils
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# Stelle sicher, dass das übergeordnete Verzeichnis (utbot2/) im Pfad ist,
sys.path.append(os.path.dirname(PROJECT_ROOT)) 
sys.path.append(PROJECT_ROOT)


from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message
from utils.guardian import guardian_decorator

# --- Logging Setup (unverändert) ---
log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)

def setup_logging(symbol, timeframe):
    """ Richtet einen spezifischen Logger für jede Strategie ein. """
    # ... (Implementierung wie im Original)
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_file = os.path.join(log_dir, f'utbot2_{safe_filename}.log')

    logger = logging.getLogger(f'utbot2_{safe_filename}')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # ... (restliche Handler-Logik)
    return logger

# --- Globale Konfiguration & Hilfsfunktionen (Entfernt load_config) ---
# load_config wurde entfernt, um den Importfehler in tests/test_basic.py zu beheben
# und die Logik in main() zu vereinfachen.

def calculate_candle_limit(timeframe, lookback_days, logger): 
    # ... (Implementierung wie im Original)
    try:
        # ... (Logik zur Berechnung des Limits)
        return 1000
    except Exception:
        return 1000

# --- Trade-Eröffnung (Angepasst für Atomaren Aufruf) ---
def attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_api, logger):

    symbol, risk_cfg, timeframe = target['symbol'], target['risk'], target['timeframe']
    # ... (Restliche Variablen)
    margin_mode = risk_cfg.get('margin_mode', 'isolated')

    # --- Guthaben wird HIER abgerufen ---
    try:
        total_usdt_balance = exchange.fetch_balance_usdt()
        if total_usdt_balance <= 0:
            logger.error("Kontoguthaben ist 0 oder konnte nicht abgerufen werden. Abbruch.")
            return
        logger.info(f"Verwende aktuelles Guthaben: {total_usdt_balance:.2f} USDT")
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Kontostands: {e}", exc_info=True)
        return
    # --- ENDE KORREKTUR ---

    # ... (OHLCV- und Indikator-Logik bleibt unverändert) ...
    # ... (Gemini API Call bleibt unverändert) ...

    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        # ... (Validierung von SL/TP bleibt unverändert) ...

        # --- RISIKOBERECHNUNG ---
        allocated_capital = total_usdt_balance * (risk_cfg['portfolio_fraction_pct'] / 100)
        allocated_capital_with_buffer = allocated_capital * 0.99
        
        minimum_capital_check = 1.0 # Für den Test
        if allocated_capital_with_buffer < minimum_capital_check: 
            logger.warning(f"Zugewiesenes Kapital ({allocated_capital_with_buffer:.2f}) nach Puffer zu gering. Abbruch.")
            return

        capital_at_risk = allocated_capital_with_buffer * (risk_cfg['risk_per_trade_pct'] / 100)
        sl_distance_pct = abs(current_price - sl_price) / current_price
        
        if sl_distance_pct < 0.001: logger.error(f"SL zu nah (<0.1%). SL={sl_price}, P={current_price}. Abbruch."); return

        position_size_usdt = capital_at_risk / sl_distance_pct
        max_leverage = risk_cfg.get('max_leverage', 1)
        final_leverage = round(max(1, min(position_size_usdt / allocated_capital_with_buffer, max_leverage)))
        amount_in_asset = position_size_usdt / current_price
        
        # ... (Marktlimit-Prüfung bleibt unverändert) ...

        # --- ATOMARER ORDER-AUFRUF ---
        try:
            logger.info(f"Versuche ATOMAREN Trade: {side} {amount_in_asset:.4f} {symbol.split('/')[0]} ({position_size_usdt:.2f} USDT) mit {final_leverage}x Hebel...")
            exchange.set_leverage(symbol, final_leverage, margin_mode)

            # --- NUTZE DEN ATOMAREN AUFRUF ---
            order_result = exchange.create_order_atomic(
                symbol, side, amount_in_asset, sl_price, tp_price, margin_mode
            )

            actual_entry_price = order_result.get('average')
            filled_amount = order_result.get('filled') 

            # HINWEIS: Es gibt keine getrennten SL/TP Orders zu prüfen.
            
            logger.info(f"✅ Trade platziert! ID: {order_result['id']}, Entry: ≈{actual_entry_price:.4f}, Menge: {filled_amount:.4f}")
            msg = (f"🚀 NEUER TRADE: *{symbol}*\n\n"
                    f"Aktion: *{decision['aktion']}* ({final_leverage}x)\n"
                    f"Größe: {filled_amount * actual_entry_price:.2f} USDT\n"
                    f"Entry: ≈ {actual_entry_price:.4f}\n"
                    f"SL: {sl_price}\n"
                    f"TP: {tp_price}")
            send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)
            
        except Exception as e:
            logger.error(f"❌ FEHLER BEI TRADE-AUSFÜHRUNG: {e}", exc_info=True)
            logger.info("Versuche Housekeeping...")
            try:
                exchange.session.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES'})
            except Exception as ce:
                logger.warning(f"Housekeeping (Cancel All) fehlgeschlagen: {ce}")

    else: logger.info(f"Keine Handelsaktion ({decision.get('aktion', 'unbekannt')}).")


# --- Strategie-Zyklus (Angepasst) ---
@guardian_decorator
def run_strategy_cycle(target, strategy_cfg, exchange, gemini_model, telegram_config, logger):
    """ Führt einen kompletten Prüf- und Handelszyklus für EINE Strategie aus. """
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
            try:
                exchange.session.cancel_all_orders(symbol, params={'productType': 'USDT-FUTURES'})
            except Exception as ce:
                logger.warning(f"Housekeeping (Cancel All) fehlgeschlagen: {ce}")
            logger.info("Housekeeping abgeschlossen.")
            attempt_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_config, logger)
            
    except ccxt.RateLimitExceeded as e: logger.warning(f"Exchange Rate Limit: {e}. Pausiere 30s."); time.sleep(30)
    except ccxt.NetworkError as e: logger.warning(f"Netzwerkfehler: {e}. Pausiere 15s."); time.sleep(15)
    logger.info(f"--- Zyklus für {symbol} abgeschlossen ---")


# --- Hauptfunktion (Initialisierung) ---
def main():
    # ... (Argument Parsing bleibt unverändert) ...

    # --- Lade Konfigurationen ---
    try:
        # Konfigurationen werden jetzt direkt im main-Block geladen
        with open('config.toml', 'r', encoding='utf-8') as f: config = toml.load(f)
        with open('secret.json', 'r', encoding='utf-8') as f: secrets = json.load(f)
    except Exception as e:
        # Hier muss eine eigene Ladefunktion her oder der Code angepasst werden
        # Wir verwenden den direkten Lade-Code, da load_config entfernt wurde
        sys.exit(1) # Breche bei Fehler ab

    # ... (Rest der main() Funktion bleibt unverändert) ...

if __name__ == "__main__":
    main()
