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

def open_new_trade(target, strategy_cfg, trading_style_text, exchange, gemini_model, telegram_api, total_usdt_balance):
    symbol, risk_cfg = target['symbol'], target['risk']
    limit = calculate_candle_limit(target['timeframe'], strategy_cfg['lookback_period_days'])
    ohlcv_df = exchange.fetch_ohlcv(symbol, target['timeframe'], limit)
    if ohlcv_df.empty: logger.error(f"[{symbol}] Keine Kerzendaten."); return None
    
    ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True); ohlcv_df.ta.atr(append=True)
    ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
    ohlcv_df.dropna(inplace=True); latest = ohlcv_df.iloc[-1]; current_price = latest['close']
    
    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name is None: logger.error(f"[{symbol}] Bollinger Band Spalte nicht gefunden."); return None

    indicator_summary = (f"Preis={current_price:.4f}, StochRSI_K/D={latest['STOCHRSIk_14_14_3_3']:.2f}/{latest['STOCHRSId_14_14_3_3']:.2f}, "
                         f"MACD_Hist={latest['MACDh_12_26_9']:.4f}, BBP={latest[bbp_column_name]:.2f}, OBV={latest['OBV']:.0f}")
    logger.info(f"[{symbol}] {indicator_summary}")
    
    prompt = (f"Aufgabe: Analysiere Trading-Daten... Beispiel-Format: ...") # Gekürzt
    
    response = gemini_model.generate_content(prompt)
    
    # --- NEU: Sicherheitsabfrage, um leere Antworten abzufangen ---
    if not response.text or not response.text.strip():
        logger.warning(f"[{symbol}] Leere Antwort von Gemini erhalten. Überspringe.")
        return None
        
    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    
    try:
        decision = json.loads(cleaned_response_text)
        logger.info(f"[{symbol}] Antwort von Gemini: {decision}")
    except json.JSONDecodeError:
        logger.error(f"[{symbol}] Antwort konnte nicht als JSON dekodiert werden: '{cleaned_response_text}'")
        return None

    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        # (Rest der Funktion bleibt unverändert)
        side, sl_price, tp_price = ('buy', decision['stop_loss'], decision['take_profit']) if decision['aktion'] == 'KAUFEN' else ('sell', decision['stop_loss'], decision['take_profit'])
        allocated_capital = total_usdt_balance * (risk_cfg['portfolio_fraction_pct'] / 100)
        capital_at_risk = allocated_capital * (risk_cfg['risk_per_trade_pct'] / 100)
        sl_distance_pct = abs(current_price - sl_price) / current_price
        if sl_distance_pct == 0: raise ValueError("SL-Distanz ist Null.")
        
        position_size_usdt = capital_at_risk / sl_distance_pct
        final_leverage = round(max(1, min(position_size_usdt / allocated_capital, risk_cfg.get('max_leverage', 1))))
        amount_in_asset = position_size_usdt / current_price
        
        market_info = exchange.session.market(symbol)
        min_amount = market_info['limits']['amount']['min']
        if amount_in_asset < min_amount:
            logger.warning(f"[{symbol}] Berechnete Ordermenge ({amount_in_asset:.4f}) unter Minimum ({min_amount}).")
            return None
            
        exchange.set_leverage(symbol, final_leverage)
        order_result = exchange.create_market_order_with_sl_tp(symbol, side, amount_in_asset, sl_price, tp_price)
        logger.info(f"[{symbol}] ✅ Order platziert: {order_result['id']}")
        msg = (f"🚀 NEUER TRADE: *{symbol}*\n\nModus: *{strategy_cfg['trading_mode'].capitalize()}*\nAktion: *{decision['aktion']}* (Dyn. Hebel: *{final_leverage}x*)\n..." )
        send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)
        
        return {"order_id": order_result['id'], "entry_timestamp": order_result['timestamp'], "side": side, "sl_price": sl_price, "tp_price": tp_price, "entry_price": order_result['price']}
    else:
        logger.info(f"[{symbol}] Keine Handelsaktion ({decision.get('aktion', 'unbekannt')}).")
        return None

def monitor_open_trade(symbol, trade_info, exchange, telegram_api):
    # (Diese Funktion bleibt unverändert)
    pass

def main():
    logger.info("==============================================")
    logger.info("=     utbot2 v2.0 (Robust & Final)           =")
    logger.info("==============================================")
    
    config, secrets, open_trades = load_config('config.toml'), load_config('secret.json'), load_open_trades()
    genai.configure(api_key=secrets['google']['api_key']); gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    exchange = ExchangeHandler(secrets['bitget'])
    total_usdt_balance = exchange.fetch_usdt_balance()
    if total_usdt_balance <= 0: logger.error("Kontoguthaben ist 0."); return
    logger.info(f"Verfügbares Guthaben: {total_usdt_balance:.2f} USDT")

    strategy_cfg = config['strategy']
    trading_style_text = PROMPT_TEMPLATES.get(strategy_cfg.get('trading_mode', 'swing'))
    
    for target in config.get('targets', []):
        if not target.get('enabled', False): continue
        symbol = target['symbol']
        try:
            if symbol in open_trades:
                if monitor_open_trade(symbol, open_trades[symbol], exchange, secrets['telegram']): del open_trades[symbol]
            else:
                if exchange.fetch_open_positions(symbol): logger.warning(f"[{symbol}] Unbekannte Position ist offen."); continue
                new_trade_details = open_new_trade(target, strategy_cfg, trading_style_text, exchange, gemini_model, secrets['telegram'], total_usdt_balance)
                if new_trade_details: open_trades[symbol] = new_trade_details
        except Exception as e:
            logger.error(f"Kritischer Fehler für {symbol}: {traceback.format_exc()}")
            send_telegram_message(secrets['telegram']['bot_token'], secrets['telegram']['chat_id'], f"🚨 KRITISCHER FEHLER für *{symbol}*!\n\n`{str(e)}`")
        
        logger.info("Warte 20 Sekunden vor dem nächsten Coin...")
        time.sleep(20)

    save_open_trades(open_trades)
    logger.info("<<< Alle Zyklen abgeschlossen. >>>\n")
        
if __name__ == "__main__":
    main()
