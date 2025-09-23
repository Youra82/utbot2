# main.py
import os, sys, json, logging, pandas as pd, traceback, time, google.generativeai as genai, pandas_ta as ta, toml
from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler()])
logger = logging.getLogger('utbot2')
TRADES_FILE = 'open_trades.json'

PROMPT_TEMPLATES = {"swing": "Swing-Trading-Strategie", "daytrade": "Day-Trading-Strategie", "scalp": "Scalping-Strategie"}

def load_open_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f: return json.load(f)
    return {}
def save_open_trades(trades):
    with open(TRADES_FILE, 'w') as f: json.dump(trades, f, indent=4)
def load_config(file_path):
    with open(file_path, 'r') as f: return toml.load(f) if file_path.endswith('.toml') else json.load(f)
def calculate_candle_limit(timeframe, lookback_days):
    if 'h' in timeframe: return int((24 / int(timeframe.replace('h', ''))) * lookback_days)
    elif 'd' in timeframe: return int(lookback_days)
    else: return int((60 / int(timeframe.replace('m', ''))) * 24 * lookback_days)

def open_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_api, total_usdt_balance):
    symbol, risk_cfg, timeframe = target['symbol'], target['risk'], target['timeframe']
    trading_style_text = PROMPT_TEMPLATES.get(strategy_cfg.get('trading_mode', 'swing'))
    
    limit = calculate_candle_limit(timeframe, strategy_cfg['lookback_period_days'])
    ohlcv_df = exchange.fetch_ohlcv(symbol, timeframe, limit)
    if ohlcv_df.empty: return None
    
    ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True); ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
    ohlcv_df.dropna(inplace=True); latest = ohlcv_df.iloc[-1]; current_price = latest['close']
    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name is None: return None
    
    indicator_summary = (f"Preis={current_price:.4f}, ...") # Gekürzt
    prompt = (f"Aufgabe: Analysiere Trading-Daten...") # Gekürzt
    
    response = gemini_model.generate_content(prompt)
    
    # --- FINALE SICHERHEITSABFRAGE ---
    if not response.parts:
        logger.warning(f"[{symbol}] Leere Antwort von Gemini (wahrscheinlich durch Safety-Filter blockiert). Überspringe.")
        return None
        
    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    
    try:
        decision = json.loads(cleaned_response_text)
        logger.info(f"[{symbol}] Antwort von Gemini: {decision}")
    except json.JSONDecodeError:
        logger.error(f"[{symbol}] Antwort konnte nicht als JSON dekodiert werden: '{cleaned_response_text}'")
        return None

    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        # ... Rest der Funktion ...
        pass
    else:
        logger.info(f"[{symbol}] Keine Handelsaktion ({decision.get('aktion', 'unbekannt')})."); return None

def monitor_open_trade(symbol, trade_info, exchange, telegram_api):
    # (unverändert)
    pass

def main():
    logger.info("==============================================")
    logger.info("=         utbot2 v2.9 (Final Stability)      =")
    logger.info("==============================================")
    
    config, secrets, open_trades = load_config('config.toml'), load_config('secret.json'), load_open_trades()
    genai.configure(api_key=secrets['google']['api_key']); gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    exchange = ExchangeHandler(secrets['bitget'])
    total_usdt_balance = exchange.fetch_usdt_balance()
    if total_usdt_balance <= 0: logger.error("Kontoguthaben ist 0."); return
    logger.info(f"Verfügbares Guthaben: {total_usdt_balance:.2f} USDT")

    strategy_cfg = config['strategy']
    
    for target in config.get('targets', []):
        if not target.get('enabled', False): continue
        symbol = target['symbol']
        try:
            if symbol in open_trades:
                if monitor_open_trade(symbol, open_trades[symbol], exchange, secrets['telegram']): del open_trades[symbol]
            else:
                if exchange.fetch_open_positions(symbol): logger.warning(f"[{symbol}] Unbekannte Position ist offen."); continue
                new_trade_details = open_new_trade(target, strategy_cfg, exchange, gemini_model, secrets['telegram'], total_usdt_balance)
                if new_trade_details: open_trades[symbol] = new_trade_details
        except Exception as e:
            logger.error(f"Kritischer Fehler für {symbol}: {traceback.format_exc()}")
            send_telegram_message(secrets['telegram']['bot_token'], secrets['telegram']['chat_id'], f"🚨 KRITISCHER FEHLER für *{symbol}*!\n\n`{str(e)}`")
        
        logger.info(f"Warte 20 Sekunden vor dem nächsten Coin...")
        time.sleep(20)

    save_open_trades(open_trades)
    logger.info("<<< Alle Zyklen abgeschlossen. >>>\n")
        
if __name__ == "__main__":
    main()
