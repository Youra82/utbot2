# main.py
import os, sys, json, logging, pandas as pd, traceback, time
import google.generativeai as genai  # <-- Zurück zu Google
import pandas_ta as ta
import toml
from google.api_core import exceptions  # <-- Gemini Rate Limit Exception
from utils.exchange_handler import ExchangeHandler
from utils.telegram_handler import send_telegram_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s UTC: %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', handlers=[logging.StreamHandler()])
logger = logging.getLogger('utbot2')
TRADES_FILE = 'open_trades.json'

PROMPT_TEMPLATES = {
    "swing": "Swing-Trading-Strategie",
    "daytrade": "Day-Trading-Strategie",
    "scalp": "Scalping-Strategie"
}

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

# --- FUNKTION ZU GEMINI ZURÜCKGEFÜHRT ---
def open_new_trade(target, strategy_cfg, exchange, gemini_model, telegram_api, total_usdt_balance):
    symbol, risk_cfg, timeframe = target['symbol'], target['risk'], target['timeframe']
    trading_style_text = PROMPT_TEMPLATES.get(strategy_cfg.get('trading_mode', 'swing'))
    
    limit = calculate_candle_limit(timeframe, strategy_cfg['lookback_period_days'])
    ohlcv_df = exchange.fetch_ohlcv(symbol, timeframe, limit)
    if ohlcv_df.empty: 
        logger.error(f"[{symbol}] Keine Kerzendaten erhalten.")
        return None
    
    # 1. Indikatoren berechnen
    ohlcv_df.ta.stochrsi(append=True); ohlcv_df.ta.macd(append=True)
    ohlcv_df.ta.bbands(append=True); ohlcv_df.ta.obv(append=True)
    ohlcv_df.dropna(inplace=True)
    
    # 2. Letzte 60 Kerzen für den Kontext vorbereiten
    data_to_send = ohlcv_df.tail(60)
    
    if data_to_send.empty:
        logger.error(f"[{symbol}] Nicht genügend Daten nach Indikatorberechnung (weniger als 60).")
        return None
        
    historical_data_string = data_to_send.round(5).to_csv(index=False, line_terminator='\n')
    
    # 3. Aktuellen Preis holen
    latest = data_to_send.iloc[-1]; current_price = latest['close']
    bbp_column_name = next((col for col in latest.index if col.startswith('BBP_')), None)
    if bbp_column_name is None: 
        logger.error(f"[{symbol}] Bollinger Band Spalte nicht gefunden.")
        return None

    # Info-Log (zeigt nur die allerletzte Kerze)
    indicator_summary = (
        f"Preis={current_price:.4f}, "
        f"StochRSI_K={latest['STOCHRSIk_14_14_3_3']:.2f}, StochRSI_D={latest['STOCHRSId_14_14_3_3']:.2f}, "
        f"MACD_Hist={latest['MACDh_12_26_9']:.4f}, BBP={latest[bbp_column_name]:.2f}, OBV={latest['OBV']:.0f}"
    )
    logger.info(f"[{symbol}] Aktuelle Indikatoren (letzte Kerze): {indicator_summary}")
    
    # 4. NEU: Gemini-Prompt mit 60-Kerzen-Kontext
    prompt = (
        "Du bist eine API, die NUR JSON zurückgibt. "
        "Analysiere die folgenden historischen Kerzendaten (im CSV-Format), um Trend, Momentum und Muster zu erkennen. "
        "Deine Antwort MUSS exakt diesem Format entsprechen und darf keinen anderen Text enthalten: "
        "'{\"aktion\": \"KAUFEN|VERKAUFEN|HALTEN\", \"stop_loss\": zahl, \"take_profit\": zahl}'\n\n"
        # --- Datenteil ---
        f"Input: strategie='{trading_style_text}', symbol='{symbol}', aktueller_preis='{current_price}'.\n\n"
        "HISTORISCHE DATEN (letzte 60 Kerzen):\n"
        f"{historical_data_string}"
    )
    
    # 5. API-Aufruf mit Gemini (zurück zum Original)
    try:
        response = gemini_model.generate_content(prompt)
    
    except exceptions.ResourceExhausted as e: # Gemini Rate Limit
        logger.warning(f"[{symbol}] Gemini API-Ratenlimit erreicht. Bot pausiert für 60 Sekunden. Fehlermeldung: {e}")
        time.sleep(60)
        return None
    except Exception as e:
        logger.error(f"[{symbol}] Kritischer Fehler bei Gemini API-Anfrage: {e}")
        return None

    if not response.parts:
        logger.warning(f"[{symbol}] Leere Antwort von Gemini (wahrscheinlich durch Safety-Filter blockiert). Überspringe.")
        return None
        
    # 6. Antwortverarbeitung (zurück zum Original mit JSON-Bereinigung)
    cleaned_response_text = response.text.replace('```json', '').replace('```', '').strip()
    
    try:
        decision = json.loads(cleaned_response_text)
        logger.info(f"[{symbol}] Antwort von KI: {decision}")
    except json.JSONDecodeError:
        logger.error(f"[{symbol}] Antwort konnte nicht als JSON dekodiert werden: '{cleaned_response_text}'")
        return None

    # 7. Risikomanagement und Order-Platzierung (unverändert)
    if decision.get('aktion') in ['KAUFEN', 'VERKAUFEN']:
        side, sl_price, tp_price = ('buy', decision.get('stop_loss'), decision.get('take_profit')) if decision['aktion'] == 'KAUFEN' else ('sell', decision.get('stop_loss'), decision.get('take_profit'))
        if not all([isinstance(sl_price, (int, float)), isinstance(tp_price, (int, float))]):
            logger.error(f"[{symbol}] Ungültige SL/TP-Werte erhalten: SL={sl_price}, TP={tp_price}")
            return None
            
        allocated_capital = total_usdt_balance * (risk_cfg['portfolio_fraction_pct'] / 100)
        capital_at_risk = allocated_capital * (risk_cfg['risk_per_trade_pct'] / 100)
        sl_distance_pct = abs(current_price - sl_price) / current_price
        if sl_distance_pct == 0: 
            logger.error(f"[{symbol}] SL-Distanz ist Null (Preis={current_price}, SL={sl_price}). Trade wird abgebrochen.")
            return None
        
        position_size_usdt = capital_at_risk / sl_distance_pct
        final_leverage = round(max(1, min(position_size_usdt / allocated_capital, risk_cfg.get('max_leverage', 1))))
        amount_in_asset = position_size_usdt / current_price
        
        market_info = exchange.session.market(symbol)
        min_amount = market_info['limits']['amount']['min']
        min_cost = market_info['limits']['cost']['min']

        if amount_in_asset < min_amount:
            logger.warning(f"[{symbol}] Berechnete Menge ({amount_in_asset:.4f}) unter Minimum ({min_amount}). Trade abgebrochen.")
            return None
        if position_size_usdt < min_cost:
            logger.warning(f"[{symbol}] Berechneter Wert ({position_size_usdt:.2f} USDT) unter Minimum ({min_cost} USDT). Trade abgebrochen.")
            return None
            
        exchange.set_leverage(symbol, final_leverage, risk_cfg.get('margin_mode', 'isolated'))
        order_result = exchange.create_market_order_with_sl_tp(symbol, side, amount_in_asset, sl_price, tp_price)
        
        entry_price = order_result.get('price') or current_price
        logger.info(f"[{symbol}] ✅ Order platziert: {order_result['id']}")
        
        msg = (f"🚀 NEUER TRADE: *{symbol}*\n\n"
               f"Modus: *{strategy_cfg['trading_mode'].capitalize()}*\n"
               f"Aktion: *{decision['aktion']}* (Dyn. Hebel: *{final_leverage}x*)\n"
               f"Größe: {position_size_usdt:.2f} USDT\n"
               f"Stop-Loss: {sl_price}\n"
               f"Take-Profit: {tp_price}")
        send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)
        
        return {"order_id": order_result['id'], "entry_timestamp": order_result['timestamp'], "side": side, "sl_price": sl_price, "tp_price": tp_price, "entry_price": entry_price}
    else:
        logger.info(f"[{symbol}] Keine Handelsaktion ({decision.get('aktion', 'unbekannt')}).")
        return None

def monitor_open_trade(symbol, trade_info, exchange, telegram_api):
    logger.info(f"[{symbol}] Überwache offenen Trade...")
    current_positions = exchange.fetch_open_positions(symbol)
    
    trade_is_open = any(str(p.get('info', {}).get('posId')) == str(trade_info.get('order_id')) for p in current_positions)
    
    if trade_is_open or (not trade_is_open and not current_positions):
        if not current_positions:
            logger.info(f"[{symbol}] Position wurde geschlossen! Suche in Trade-Historie...")

            trade_history = exchange.fetch_trade_history(symbol, trade_info['entry_timestamp'])
            
            closing_trade = None
            for t in reversed(trade_history):
                if t.get('order') == trade_info.get('order_id') and t.get('side') != trade_info.get('side'):
                    closing_trade = t
                    break

            if not closing_trade:
                logger.warning(f"[{symbol}] Konnte Schließungs-Trade nicht finden (Order-ID: {trade_info.get('order_id')}). Warte auf nächsten Zyklus.")
                return False 
                
            exit_price = closing_trade['price']
            entry_price = trade_info['entry_price']
            amount = closing_trade['amount']
            fee = closing_trade.get('fee', {}).get('cost', 0)

            if trade_info['side'] == 'buy':
                pnl = (exit_price - entry_price) * amount - fee
                is_tp = exit_price >= trade_info['tp_price']
            else: # 'sell'
                pnl = (entry_price - exit_price) * amount - fee
                is_tp = exit_price <= trade_info['tp_price']

            if is_tp:
                msg = f"✅ *TAKE-PROFIT GETROFFEN: {symbol}*\n\nGeschlossen bei: {exit_price}\nGeschätzter Gewinn: {pnl:.2f} USDT"
            else:
                msg = f"🛑 *STOP-LOSS AUSGELÖST: {symbol}*\n\nGeschlossen bei: {exit_price}\nGeschätzter Verlust: {pnl:.2f} USDT"
            
            send_telegram_message(telegram_api['bot_token'], telegram_api['chat_id'], msg)
            return True 
        else:
            logger.info(f"[{symbol}] Position ist weiterhin offen.")
            return False 
    
    logger.warning(f"[{symbol}] Trade-Mismatch. 'trade_is_open' ist False, aber es existieren Positionen.")
    return False

# --- FUNKTION ZU GEMINI ZURÜCKGEFÜHRT ---
def main():
    logger.info("==============================================")
    logger.info("=   utbot2 v3.5 (Gemini / 60-Candle-Ctx)   =")
    logger.info("==============================================")
    
    config, secrets, open_trades = load_config('config.toml'), load_config('secret.json'), load_open_trades()
    
    # --- NEU: Gemini-Client initialisieren ---
    try:
        genai.configure(api_key=secrets['google']['api_key'])
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini-Client erfolgreich initialisiert.")
    except KeyError:
        logger.error("FATAL: 'google' oder 'api_key' nicht in secret.json gefunden!")
        return
    except Exception as e:
        logger.error(f"FATAL: Fehler beim Initialisieren des Gemini-Clients: {e}")
        return
    
    exchange = ExchangeHandler(secrets['bitget'])
    total_usdt_balance = exchange.fetch_usdt_balance()
    if total_usdt_balance <= 0: logger.error("Kontoguthaben ist 0. Bot stoppt."); return
    logger.info(f"Verfügbares Guthaben: {total_usdt_balance:.2f} USDT")

    strategy_cfg = config['strategy']
    
    for target in config.get('targets', []):
        if not target.get('enabled', False): continue
        symbol = target['symbol']
        try:
            if symbol in open_trades:
                if monitor_open_trade(symbol, open_trades[symbol], exchange, secrets['telegram']): 
                    del open_trades[symbol]
            else:
                if exchange.fetch_open_positions(symbol): 
                    logger.warning(f"[{symbol}] Unbekannte Position ist offen (manueller Trade?). Bot wird nicht handeln.")
                    continue
                
                # --- Geänderter Funktionsaufruf ---
                new_trade_details = open_new_trade(
                    target, 
                    strategy_cfg, 
                    exchange, 
                    gemini_model,     # <--- Geändert
                    secrets['telegram'], 
                    total_usdt_balance
                )
                
                if new_trade_details: 
                    open_trades[symbol] = new_trade_details
                    
        except Exception as e:
            logger.error(f"Kritischer Fehler für {symbol}: {traceback.format_exc()}")
            send_telegram_message(secrets['telegram']['bot_token'], secrets['telegram']['chat_id'], f"🚨 KRITISCHER FEHLER für *{symbol}*!\n\n`{str(e)}`")
        
        logger.info(f"Warte 20 Sekunden vor dem nächsten Coin...")
        time.sleep(20) 

    save_open_trades(open_trades)
    logger.info("<<< Alle Zyklen abgeschlossen. >>>\n")
        
if __name__ == "__main__":
    main()
