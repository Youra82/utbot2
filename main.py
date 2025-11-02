# utbot2/main.py (Version 4.4 - Mit neuem 3-Schritt-Aufruf)
import logging
import json
import time
import os
import ccxt
import pandas as pd
import toml

from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message, format_trade_message
from utils.indicator_handler import calculate_indicators
# Annahme: Gemini API ist korrekt importiert
try:
    from utils.gemini_handler import get_trade_decision
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def setup_logging(symbol, timeframe):
    """Konfiguriert den Logger für das Skript."""
    logger = logging.getLogger(f'utbot2_{symbol.replace("/", "").replace(":", "")}_{timeframe}')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch_formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s: [%(name)s] %(message)s', datefmt='%H:%M:%S')
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)
    return logger


def calculate_amount_and_risk(target_config, balance_usdt, current_price, sl_price):
    """Berechnet die Ordergröße und überprüft das Risiko."""
    
    portfolio_fraction = target_config['risk']['portfolio_fraction_pct'] / 100.0
    risk_capital = balance_usdt * portfolio_fraction
    leverage = target_config['risk']['max_leverage']
    
    if sl_price == 0:
        position_size_usdt = risk_capital * leverage
    else:
        sl_distance_pct = abs(current_price - sl_price) / current_price
        position_size_usdt = risk_capital / sl_distance_pct
        
        max_size_by_leverage = balance_usdt * leverage
        
        if position_size_usdt > max_size_by_leverage:
            position_size_usdt = max_size_by_leverage
            
    if position_size_usdt <= 0:
        return 0.0, 0.0
        
    amount = position_size_usdt / current_price
    
    logger.info(f"Verwende aktuelles Guthaben: {balance_usdt:.2f} USDT")
    logger.info(f"Risiko-Kapital: {risk_capital:.2f} USDT, Geplante Positionsgröße (USD): {position_size_usdt:.2f}")

    return amount, position_size_usdt


def attempt_new_trade(target_config, strategy_config, exchange, gemini_model, telegram_config, logger):
    """
    Versucht, einen neuen Trade zu eröffnen, wenn die KI ein Signal gibt.
    """
    symbol = target_config['symbol']
    timeframe = target_config['timeframe']
    
    # --- 1. Daten laden und Indikatoren berechnen ---
    df = exchange.fetch_ohlcv(symbol, timeframe, limit=1440) 
    if len(df) < 60:
        logger.warning(f"Nicht genügend Daten ({len(df)}) für {symbol} verfügbar. Überspringe Zyklus.")
        return 
        
    df = calculate_indicators(df)
    last_row = df.iloc[-1]
    
    logger.info(f"Aktuelle Indikatoren (letzte Kerze): P={last_row['close']:.4f}, StochK={last_row['stochk']:.1f}, StochD={last_row['stochd']:.1f}, MACD_H={last_row['macd_hist']:.4f}, BBP={last_row['bbp']:.2f}, OBV={last_row['obv']:.0f}")
    
    # --- 2. KI-Entscheidung einholen ---
    decision = None
    
    try:
        if GEMINI_AVAILABLE:
            prompt = strategy_config['prompt_template'].format(
                symbol=symbol,
                timeframe=timeframe,
                data=df.iloc[-strategy_config['lookback_period']:].to_json(),
                aktueller_preis=last_row['close']
            )
            logger.info("Sende Anfrage an Gemini...")
            gemini_response = gemini_model.generate_content(prompt)
            logger.info("Antwort von Gemini erhalten.")
            decision_text = gemini_response.text.strip()
            
            if not decision_text.startswith('{') or not decision_text.endswith('}'):
                start = decision_text.find('{')
                end = decision_text.rfind('}')
                if start != -1 and end != -1:
                    decision_text = decision_text[start:end+1]
                
            decision = json.loads(decision_text)
            
        else:
            gemini_response = gemini_model.generate_content(None)
            decision_text = gemini_response.text.strip()
            decision = json.loads(decision_text)
            
        logger.info(f"KI-Entscheidung: {decision}")
        
    except Exception as e:
        logger.error(f"FEHLER beim Abrufen/Parsen der KI-Entscheidung: {e}")
        return

    # --- 3. Trade ausführen ---
    action = decision.get('aktion', 'HALTEN')
    
    if action not in ['KAUFEN', 'VERKAUFEN']:
        logger.info(f"KI signalisiert '{action}'. Kein Trade.")
        return 
        
    side = 'buy' if action == 'KAUFEN' else 'sell'
    sl_price = float(decision.get('stop_loss', 0))
    tp_price = float(decision.get('take_profit', 0))
    
    balance_usdt = exchange.fetch_balance_usdt()
    if balance_usdt < target_config['risk']['min_balance_usdt']:
        logger.warning(f"Guthaben ({balance_usdt:.2f} USDT) liegt unter Minimum ({target_config['risk']['min_balance_usdt']} USDT). Kein Trade.")
        return 
        
    current_price = last_row['close']
    amount, position_size_usdt = calculate_amount_and_risk(target_config, balance_usdt, current_price, sl_price)
    
    if amount == 0:
        logger.warning("Berechnete Ordergröße ist Null. Überspringe Trade.")
        return

    logger.info(f"Versuche 3-SCHRITT Trade: {side} {amount:.4f} {symbol.split('/')[0]} ({position_size_usdt:.2f} USDT) mit {target_config['risk']['max_leverage']}x Hebel...")

    try:
        exchange.set_leverage(symbol, target_config['risk']['max_leverage'], target_config['risk']['margin_mode'])
        
        # --- KRITISCHE ÄNDERUNG: Dreischritt-Aufruf anstatt Atomic ---
        order_result = exchange.create_market_order_with_sl_tp(
            symbol,
            side,
            amount,
            sl_price,
            tp_price,
            target_config['risk']['margin_mode']
        )
        
        # --- Benachrichtigung ---
        entry_price = order_result.get('average', current_price)
        msg = format_trade_message(symbol, side, entry_price, sl_price, tp_price, amount, order_result.get('filled', amount))
        send_telegram_message(telegram_config, msg)
        logger.info(f"✅ Trade erfolgreich ausgeführt und Telegram gesendet.")
        
    except Exception as e:
        logger.error(f"❌ FEHLER BEI TRADE-AUSFÜHRUNG: {e}", exc_info=False)

    logger.info("Versuche Housekeeping...")
    exchange.cleanup_all_open_orders(symbol)


def run_strategy_cycle(target_config, strategy_config, exchange, gemini_model, telegram_config, logger):
    """
    Führt einen kompletten Zyklus der Handelsstrategie aus (Trade prüfen oder neu eröffnen).
    """
    symbol = target_config['symbol']
    
    logger.info(f"--- Starte Zyklus für {symbol} ({target_config['timeframe']}) ---")
    
    try:
        open_positions = exchange.fetch_open_positions(symbol)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen offener Positionen: {e}")
        return 
        
    exchange.cleanup_all_open_orders(symbol)

    if not open_positions:
        logger.info("Keine offene Position gefunden.")
        attempt_new_trade(target_config, strategy_config, exchange, gemini_model, telegram_config, logger)
        
    else:
        logger.info(f"Offene Position ({open_positions[0]['side']}, Größe: {open_positions[0]['contracts']}) gefunden. Überspringe neuen Trade.")
        
    logger.info(f"--- Zyklus für {symbol} abgeschlossen ---")


def load_config(file_path='config.toml'):
    """Lädt die TOML-Konfiguration."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except Exception:
        return None


def load_secrets(file_path='secret.json'):
    """Lädt die JSON-Geheimnisse."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def main():
    """Hauptfunktion des Bots."""
    config = load_config()
    secrets = load_secrets()
    
    if not config or not secrets:
        return 
        
    exchange_handler = ExchangeHandler()
    
    try:
        bitget_config = secrets['bitget']
        exchange_handler.session = ccxt.bitget({
            'apiKey': bitget_config['apiKey'],
            'secret': bitget_config['secret'],
            'password': bitget_config['password'],
            'options': {'defaultType': 'swap'},
        })
        exchange_handler.session.load_markets()
    except Exception as e:
        print(f"FEHLER: Bitget-Initialisierung fehlgeschlagen: {e}")
        return
        
    # Gemini Model Mock oder Live initialisieren (Platzhalter)
    gemini_model = None
    if GEMINI_AVAILABLE:
        try:
            from utils.gemini_handler import get_gemini_model
            gemini_model = get_gemini_model() 
        except Exception:
            pass
            
    if not gemini_model:
        return
        
    telegram_config = secrets.get('telegram', {})
    
    for target in config.get('targets', []):
        if target.get('enabled', False):
            symbol = target['symbol']
            timeframe = target['timeframe']
            logger = setup_logging(symbol, timeframe)
            
            try:
                run_strategy_cycle(target, config['strategy'], exchange_handler, gemini_model, telegram_config, logger)
            except Exception as e:
                logger.error(f"Unbehandelter Fehler im Hauptzyklus für {symbol}: {e}", exc_info=True)
                
    

if __name__ == '__main__':
    if os.environ.get('UTBOT_TEST_MODE') != 'true':
        main()
