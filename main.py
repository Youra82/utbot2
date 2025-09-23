# main.py
import os, sys, json, logging, pandas as pd, traceback, time, google.generativeai as genai, pandas_ta as ta, toml
from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler()])
logger = logging.getLogger('utbot2')
TRADES_FILE = 'open_trades.json'

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
    
    limit = calculate_candle_limit(timeframe, strategy_cfg['lookback_period_days'])
    ohlcv_df = exchange.fetch_ohlcv(symbol, timeframe, limit)
    if ohlcv_df.empty: return None
    
    ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True); ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
    ohlcv_df.dropna(inplace=True); latest = ohlcv_df.iloc[-1]; current_price = latest['close']
    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name is None: return None
    
    indicator_summary = (f"Preis={current_price:.4f}, StochRSI_K={latest['STOCHRSIk_14_14_3_3']:.2f}, StochRSI_D={latest['STOCHRSId_14_14_3_3']:.2f}, "
                         f"MACD_Hist={latest['MACDh_12_26_9']:.4f}, BBP={latest[bbp_column_name]:.2f}, OBV={latest['OBV']:.0f}")
    logger.info(f"[{symbol}] {indicator_summary}")
    
    # --- RADIKAL NEUER PROMPT ---
    prompt = (
        "Du bist eine API, die JSON zurückgibt. "
        "Analysiere die folgenden Trading-Daten und gib eine JSON-Antwort mit den Schlüsseln 'aktion', 'stop_loss' und 'take_profit' zurück. "
        f"Input-Daten: {{'symbol': '{symbol}', 'strategie': '{strategy_cfg['trading_mode']}', 'indikatoren': '{indicator_summary}'}} "
        "Antworte NUR mit dem JSON-Objekt."
    )
    
    response = gemini_model.generate_content(prompt)
    if not response.parts:
        logger.warning(f"[{symbol}] Leere Antwort von Gemini."); return None
        
    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    
    try:
        decision = json.loads(cleaned_response_text)
        logger.info(f"[{symbol}] Antwort von Gemini: {decision}")
    except json.JSONDecodeError:
        logger.error(f"[{symbol}] Antwort konnte nicht als JSON dekodiert werden: '{cleaned_response_text}'"); return None

    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        # ... (Rest der Funktion bleibt unverändert) ...
        pass
    else:
        logger.info(f"[{symbol}] Keine Handelsaktion ({decision.get('aktion', 'unbekannt')})."); return None

# ... (Rest des Codes bleibt unverändert) ...

def monitor_open_trade(symbol, trade_info, exchange, telegram_api):
    # (unverändert)
    pass

def main():
    logger.info("==============================================")
    logger.info("=         utbot2 v2.6 (Final Attempt)        =")
    logger.info("==============================================")
    # ... (Rest der main-Funktion bleibt unverändert) ...
    pass
        
if __name__ == "__main__":
    main()
