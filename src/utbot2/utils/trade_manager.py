# /root/utbot2/src/utbot2/utils/trade_manager.py
import json
import logging
import os
import time
from datetime import datetime, timedelta

import ccxt
import numpy as np
import pandas as pd
import ta 
import math

# Imports angepasst auf utbot2
from utbot2.strategy.ichimoku_engine import IchimokuEngine
from utbot2.strategy.supertrend_engine import SupertrendEngine  # NEU: Supertrend für MTF
from utbot2.strategy.trade_logic import get_titan_signal
from utbot2.utils.exchange import Exchange
from utbot2.utils.telegram import send_message
from utbot2.utils.timeframe_utils import determine_htf

# --------------------------------------------------------------------------- #
# Pfade
# --------------------------------------------------------------------------- #
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
ARTIFACTS_PATH = os.path.join(PROJECT_ROOT, 'artifacts')
DB_PATH = os.path.join(ARTIFACTS_PATH, 'db')
TRADE_LOCK_FILE = os.path.join(DB_PATH, 'trade_lock.json')

# Hilfsklasse für Bias
class Bias:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

# --------------------------------------------------------------------------- #
# Trade-Lock-Hilfsfunktionen
# --------------------------------------------------------------------------- #
def load_or_create_trade_lock():
    os.makedirs(DB_PATH, exist_ok=True)
    if os.path.exists(TRADE_LOCK_FILE):
        with open(TRADE_LOCK_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_trade_lock(trade_lock):
    with open(TRADE_LOCK_FILE, 'w') as f:
        json.dump(trade_lock, f, indent=4)

def is_trade_locked(symbol_timeframe):
    trade_lock = load_or_create_trade_lock()
    lock_time_str = trade_lock.get(symbol_timeframe)
    if lock_time_str:
        lock_time = datetime.strptime(lock_time_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() < lock_time:
            return True
    return False

def set_trade_lock(symbol_timeframe, lock_duration_minutes=60):
    lock_time = datetime.now() + timedelta(minutes=lock_duration_minutes)
    trade_lock = load_or_create_trade_lock()
    trade_lock[symbol_timeframe] = lock_time.strftime("%Y-%m-%d %H:%M:%S")
    save_trade_lock(trade_lock)

def calculate_lock_duration(timeframe):
    """Berechnet dynamische Trade Lock Duration basierend auf Timeframe (2-3x Timeframe)."""
    tf_minutes = {
        '5m': 5, '15m': 15, '30m': 30, 
        '1h': 60, '2h': 120, '4h': 240, 
        '6h': 360, '1d': 1440
    }
    base_minutes = tf_minutes.get(timeframe, 60)
    # 2.5x Timeframe als Lock (Balance zwischen zu kurz und zu lang)
    return int(base_minutes * 2.5)

# --------------------------------------------------------------------------- #
# MTF-Bias Bestimmung (Supertrend auf HTF)
# --------------------------------------------------------------------------- #
def get_market_bias(exchange, symbol, htf, logger, supertrend_settings=None):
    """
    Bestimmt den Markt-Bias basierend auf dem Supertrend des HTF.
    
    Der Supertrend ist ein Trend-Following-Indikator der klar anzeigt,
    ob der übergeordnete Trend bullish oder bearish ist.
    
    Args:
        exchange: Exchange-Objekt für Datenabfrage
        symbol: Trading-Symbol
        htf: Higher Timeframe (z.B. '4h' wenn wir auf '1h' traden)
        logger: Logger-Objekt
        supertrend_settings: Dict mit 'supertrend_atr_period' und 'supertrend_multiplier'
    
    Returns:
        Bias.BULLISH, Bias.BEARISH oder Bias.NEUTRAL
    """
    try:
        # Wir brauchen genug Daten für den Supertrend (ATR Periode + Buffer)
        htf_data = exchange.fetch_recent_ohlcv(symbol, htf, limit=100)
        if htf_data.empty or len(htf_data) < 30:
            logger.warning(f"MTF-Check: Nicht genügend Daten auf {htf} verfügbar.")
            return Bias.NEUTRAL

        # Supertrend berechnen
        supertrend_settings = supertrend_settings or {}
        engine = SupertrendEngine(settings=supertrend_settings)
        df = engine.process_dataframe(htf_data)
        
        # Aktuellen Trend abrufen
        trend = engine.get_trend(df)
        
        last_candle = df.iloc[-1]
        close = last_candle['close']
        supertrend_value = last_candle.get('supertrend', None)
        direction = last_candle.get('supertrend_direction', None)
        
        if pd.isna(supertrend_value) or pd.isna(direction):
            logger.warning(f"MTF-Check ({htf}): Supertrend noch nicht berechenbar.")
            return Bias.NEUTRAL
        
        # Abstand zum Supertrend für Logging
        distance_pct = abs(close - supertrend_value) / close * 100
        
        if trend == "BULLISH":
            logger.info(f"MTF-Check ({htf}): 🟢 BULLISH (Supertrend bei {supertrend_value:.2f}, Preis {distance_pct:.2f}% darüber)")
            return Bias.BULLISH
        elif trend == "BEARISH":
            logger.info(f"MTF-Check ({htf}): 🔴 BEARISH (Supertrend bei {supertrend_value:.2f}, Preis {distance_pct:.2f}% darunter)")
            return Bias.BEARISH
        else:
            logger.info(f"MTF-Check ({htf}): ⚪ NEUTRAL")
            return Bias.NEUTRAL

    except Exception as e:
        logger.error(f"Fehler bei der MTF-Bias-Bestimmung (Supertrend): {e}")
        return Bias.NEUTRAL

# --------------------------------------------------------------------------- #
# Housekeeper
# --------------------------------------------------------------------------- #
def housekeeper_routine(exchange, symbol, logger):
    try:
        logger.info(f"Housekeeper: Starte Aufräumroutine für {symbol}...")
        exchange.cancel_all_orders_for_symbol(symbol)
        time.sleep(2)

        position = exchange.fetch_open_positions(symbol)
        if position:
            pos_info = position[0]
            close_side = 'sell' if pos_info['side'] == 'long' else 'buy'
            logger.warning(f"Housekeeper: Schließe verwaiste Position ({pos_info['side']} {pos_info['contracts']})...")
            exchange.create_market_order(symbol, close_side, float(pos_info['contracts']), {'reduceOnly': True})
            time.sleep(3)

        if exchange.fetch_open_positions(symbol):
            logger.error("Housekeeper: Position konnte nicht geschlossen werden!")
        else:
            logger.info(f"Housekeeper: {symbol} ist jetzt sauber.")
        return True
    except Exception as e:
        logger.error(f"Housekeeper-Fehler: {e}", exc_info=True)
        return False

# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #
def check_and_open_new_position(exchange, model, scaler, params, telegram_config, logger):
    symbol = params['market']['symbol']
    timeframe = params['market']['timeframe']
    htf = params['market']['htf']
    symbol_timeframe = f"{symbol.replace('/', '-')}_{timeframe}"

    if is_trade_locked(symbol_timeframe):
        logger.info(f"Trade für {symbol_timeframe} gesperrt – überspringe.")
        return

    try:
        logger.info(f"Prüfe vollständiges Ichimoku-Signal für {symbol} ({timeframe}) mit Supertrend-Filter auf {htf}...")
        
        # Supertrend-Settings aus Config holen
        strategy_params = params.get('strategy', {})
        supertrend_settings = {
            'supertrend_atr_period': strategy_params.get('supertrend_atr_period', 10),
            'supertrend_multiplier': strategy_params.get('supertrend_multiplier', 3.0)
        }
        
        # MTF-Bias via Supertrend
        market_bias = get_market_bias(exchange, symbol, htf, logger, supertrend_settings)

        recent_data = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=200)
        if recent_data.empty or len(recent_data) < 100:
            logger.warning("Nicht genügend OHLCV-Daten – überspringe.")
            return

        # ATR für Stop Loss Berechnung
        atr_indicator = ta.volatility.AverageTrueRange(high=recent_data['high'], low=recent_data['low'], close=recent_data['close'], window=14)
        recent_data['atr'] = atr_indicator.average_true_range()
        
        # Ichimoku Indikatoren (vollständig)
        engine = IchimokuEngine(settings=strategy_params)
        processed_data = engine.process_dataframe(recent_data)
        
        current_candle = processed_data.iloc[-1]

        # Signal abrufen (mit ADX und Volume bereits im DataFrame)
        signal_side, signal_price = get_titan_signal(processed_data, current_candle, params, market_bias)

        if not signal_side:
            logger.info("Kein Signal – überspringe.")
            return

        if exchange.fetch_open_positions(symbol):
            logger.info("Position bereits offen – überspringe.")
            return

        # Risk Management
        risk_params = params.get('risk', {})
        leverage = risk_params.get('leverage', 10)
        margin_mode = risk_params.get('margin_mode', 'isolated')
        if not exchange.set_leverage(symbol, leverage): return
        if not exchange.set_margin_mode(symbol, margin_mode): return

        balance = exchange.fetch_balance_usdt()
        if balance <= 0:
            logger.error("Kein USDT-Guthaben.")
            return

        ticker = exchange.fetch_ticker(symbol)
        estimated_entry_price = signal_price or ticker['last']
        
        rr = risk_params.get('risk_reward_ratio', 2.0)
        risk_pct = risk_params.get('risk_per_trade_pct', 1.0) / 100.0
        risk_usdt = balance * risk_pct

        atr_multiplier_sl = risk_params.get('atr_multiplier_sl', 2.0)
        min_sl_pct = risk_params.get('min_sl_pct', 0.5) / 100.0

        current_atr = current_candle.get('atr')
        if pd.isna(current_atr) or current_atr <= 0:
            sl_distance = estimated_entry_price * (1.0 / leverage)
        else:
            sl_distance_atr = current_atr * atr_multiplier_sl
            sl_distance_min = estimated_entry_price * min_sl_pct
            sl_distance = max(sl_distance_atr, sl_distance_min)

        if sl_distance <= 0: return

        if signal_side == 'buy':
            pos_side = 'buy'
            tsl_side = 'sell'
        else:
            pos_side = 'sell'
            tsl_side = 'buy'

        sl_distance_pct_equivalent = sl_distance / estimated_entry_price
        calculated_notional_value = risk_usdt / sl_distance_pct_equivalent
        amount = calculated_notional_value / estimated_entry_price
        
        min_amount = exchange.markets[symbol].get('limits', {}).get('amount', {}).get('min', 0.0)
        if amount < min_amount:
            logger.error(f"Ordergröße {amount} < Mindestbetrag {min_amount}.")
            return

        # Orders
        logger.info(f"Eröffne {pos_side.upper()}-Position: {amount:.6f} @ ~${estimated_entry_price:.6f} | Risk: {risk_usdt:.2f} USDT")
        order_params = {'marginMode': margin_mode}
        entry_order = exchange.create_market_order(symbol, pos_side, amount, order_params)
        if not entry_order: return
        
        # *** KRITISCH: Hole den ECHTEN Fill-Preis ***
        time.sleep(1)  # Kurz warten damit Order settled
        actual_entry_price = entry_order.get('average') or entry_order.get('price') or estimated_entry_price
        
        # Prüfe ob Fill-Preis sinnvoll ist
        price_deviation_pct = abs(actual_entry_price - estimated_entry_price) / estimated_entry_price * 100
        if price_deviation_pct > 5.0:  # Mehr als 5% Abweichung = Problem
            logger.warning(f"⚠️ Fill-Preis {actual_entry_price} weicht {price_deviation_pct:.2f}% vom erwarteten Preis ab!")
            actual_entry_price = estimated_entry_price  # Fallback
        
        logger.info(f"✅ Order gefüllt @ ${actual_entry_price:.6f} (Diff: {price_deviation_pct:.3f}%)")
        
        # Recalculate SL/TP mit ECHTEM Entry Price
        if pd.isna(current_atr) or current_atr <= 0:
            sl_distance = actual_entry_price * (1.0 / leverage)
        else:
            sl_distance_atr = current_atr * atr_multiplier_sl
            sl_distance_min = actual_entry_price * min_sl_pct
            sl_distance = max(sl_distance_atr, sl_distance_min)
        
        if signal_side == 'buy':
            sl_price = actual_entry_price - sl_distance
            tp_price = actual_entry_price + sl_distance * rr
        else:
            sl_price = actual_entry_price + sl_distance
            tp_price = actual_entry_price - sl_distance * rr

        time.sleep(2)
        position = exchange.fetch_open_positions(symbol)
        if not position: return

        pos_info = position[0]
        contracts = float(pos_info['contracts'])

        sl_rounded = float(exchange.exchange.price_to_precision(symbol, sl_price))
        tp_rounded = float(exchange.exchange.price_to_precision(symbol, tp_price))
        exchange.place_trigger_market_order(symbol, tsl_side, contracts, sl_rounded, {'reduceOnly': True})

        act_rr = risk_params.get('trailing_stop_activation_rr', 1.5)
        callback_pct = risk_params.get('trailing_stop_callback_rate_pct', 0.5) / 100.0
        
        if pos_side == 'buy':
            act_price = actual_entry_price + sl_distance * act_rr
        else:
            act_price = actual_entry_price - sl_distance * act_rr
            
        exchange.place_trailing_stop_order(symbol, tsl_side, contracts, act_price, callback_pct, {'reduceOnly': True})

        # Dynamischer Trade Lock basierend auf Timeframe
        lock_duration = calculate_lock_duration(timeframe)
        set_trade_lock(symbol_timeframe, lock_duration)
        logger.info(f"Trade Lock gesetzt für {lock_duration} Minuten")

        if telegram_config and telegram_config.get('bot_token') and telegram_config.get('chat_id'):
            msg = (
                f"🎯 UTBOT2 ICHIMOKU: {symbol} ({timeframe}) [MTF: {market_bias}]\n"
                f"- Richtung: {pos_side.upper()}\n"
                f"- Entry: ${actual_entry_price:.6f}\n"
                f"- SL: ${sl_rounded:.6f}\n"
                f"- TP: ${tp_rounded:.6f}\n"
                f"- Risk: {risk_usdt:.2f} USDT\n"
                f"- Lock: {lock_duration}min"
            )
            send_message(telegram_config['bot_token'], telegram_config['chat_id'], msg)

        logger.info("✅ Trade-Eröffnung erfolgreich abgeschlossen.")

    except ccxt.InsufficientFunds as e:
        logger.error(f"InsufficientFunds: {e}")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}", exc_info=True)
        housekeeper_routine(exchange, symbol, logger)

def manage_open_position(exchange, position, params, telegram_config, logger):
    """Aktives Position Management: Prüft auf Gegensignal und MTF-Bias Änderung."""
    symbol = params['market']['symbol']
    timeframe = params['market']['timeframe']
    htf = params['market']['htf']
    
    try:
        pos_side = position['side']  # 'long' oder 'short'
        contracts = float(position['contracts'])
        
        logger.info(f"📊 Position Management: {pos_side.upper()} {contracts} Kontrakte")
        
        # Hole aktuelle Daten für Signal-Check
        recent_data = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=200)
        if recent_data.empty or len(recent_data) < 100:
            return
        
        # Berechne Indikatoren
        smc_params = params.get('strategy', {})
        atr_indicator = ta.volatility.AverageTrueRange(high=recent_data['high'], low=recent_data['low'], close=recent_data['close'], window=14)
        recent_data['atr'] = atr_indicator.average_true_range()
        
        adx_indicator = ta.trend.ADXIndicator(high=recent_data['high'], low=recent_data['low'], close=recent_data['close'], window=14)
        recent_data['adx'] = adx_indicator.adx()
        
        engine = IchimokuEngine(settings=smc_params)
        processed_data = engine.process_dataframe(recent_data)
        current_candle = processed_data.iloc[-1]
        
        # Prüfe aktuellen MTF Bias
        market_bias = get_market_bias(exchange, symbol, htf, logger)
        
        # Check auf Gegensignal
        signal_side, _ = get_titan_signal(processed_data, current_candle, params, market_bias=None)  # Ohne Bias für echtes Signal
        
        if signal_side:
            # Starkes Gegensignal erkannt
            if (pos_side == 'long' and signal_side == 'sell') or (pos_side == 'short' and signal_side == 'buy'):
                logger.warning(f"⚠️ GEGENSIGNAL erkannt! Position: {pos_side.upper()}, Signal: {signal_side.upper()}")
                logger.warning(f"🔄 Schließe Position vorzeitig...")
                
                close_side = 'sell' if pos_side == 'long' else 'buy'
                close_order = exchange.create_market_order(symbol, close_side, contracts, {'reduceOnly': True})
                
                if close_order:
                    logger.info("✅ Position erfolgreich wegen Gegensignal geschlossen")
                    
                    if telegram_config and telegram_config.get('bot_token') and telegram_config.get('chat_id'):
                        msg = (
                            f"🔄 UTBOT2: Position geschlossen ({symbol})\n"
                            f"Grund: Gegensignal erkannt\n"
                            f"Position: {pos_side.upper()} → Signal: {signal_side.upper()}"
                        )
                        send_message(telegram_config['bot_token'], telegram_config['chat_id'], msg)
                    
                    # Storniere alle verbleibenden Orders
                    time.sleep(2)
                    exchange.cancel_all_orders_for_symbol(symbol)
                return
        
        # Prüfe ob MTF-Bias sich gedreht hat
        if market_bias and market_bias != "NEUTRAL":
            if (pos_side == 'long' and market_bias == 'BEARISH') or (pos_side == 'short' and market_bias == 'BULLISH'):
                logger.warning(f"⚠️ HTF-BIAS hat sich gedreht! Position: {pos_side.upper()}, HTF: {market_bias}")
                logger.warning(f"📉 Schließe Position wegen MTF-Bias Änderung...")
                
                close_side = 'sell' if pos_side == 'long' else 'buy'
                close_order = exchange.create_market_order(symbol, close_side, contracts, {'reduceOnly': True})
                
                if close_order:
                    logger.info("✅ Position erfolgreich wegen MTF-Bias geschlossen")
                    
                    if telegram_config and telegram_config.get('bot_token') and telegram_config.get('chat_id'):
                        msg = (
                            f"📉 UTBOT2: Position geschlossen ({symbol})\n"
                            f"Grund: HTF-Bias Änderung\n"
                            f"Position: {pos_side.upper()} → HTF: {market_bias}"
                        )
                        send_message(telegram_config['bot_token'], telegram_config['chat_id'], msg)
                    
                    time.sleep(2)
                    exchange.cancel_all_orders_for_symbol(symbol)
                return
        
        logger.info("✅ Position OK - keine Action erforderlich")
        
    except Exception as e:
        logger.error(f"Fehler im Position Management: {e}", exc_info=True)

def full_trade_cycle(exchange, model, scaler, params, telegram_config, logger):
    symbol = params['market']['symbol']
    try:
        pos = exchange.fetch_open_positions(symbol)
        if pos:
            logger.info(f"Position offen – Aktives Management...")
            manage_open_position(exchange, pos[0], params, telegram_config, logger)
        else:
            housekeeper_routine(exchange, symbol, logger)
            check_and_open_new_position(exchange, model, scaler, params, telegram_config, logger)
    except Exception as e:
        logger.error(f"Fehler im Zyklus: {e}", exc_info=True)
        time.sleep(5)
