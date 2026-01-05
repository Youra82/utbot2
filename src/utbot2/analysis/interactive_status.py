#!/usr/bin/env python3
"""
Interactive Charts für UtBot2 - Ichimoku Cloud Strategie mit Backtest-Ergebnissen
Zeigt Candlestick-Chart mit:
- Ichimoku Indikatoren (Tenkan, Kijun, Kumo, Chikou)
- Entry/Exit Long/Short Signale
- Equity Curve (Kontoverlauf)
- PnL Statistiken
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from utbot2.strategy.ichimoku_engine import IchimokuEngine
from utbot2.strategy.trade_logic import get_titan_signal
from utbot2.utils.exchange import Exchange

def setup_logging():
    logger = logging.getLogger('interactive_status')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(ch)
    return logger

logger = setup_logging()

def get_config_files():
    """Sucht alle Konfigurationsdateien auf"""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'utbot2', 'strategy', 'configs')
    if not os.path.exists(configs_dir):
        return []
    
    configs = []
    for filename in sorted(os.listdir(configs_dir)):
        if filename.startswith('config_') and filename.endswith('.json'):
            filepath = os.path.join(configs_dir, filename)
            configs.append((filename, filepath))
    
    return configs

def select_configs():
    """Zeigt durchnummerierte Konfigurationsdateien und lässt User wählen"""
    configs = get_config_files()
    
    if not configs:
        logger.error("Keine Konfigurationsdateien gefunden!")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("Verfügbare Konfigurationen:")
    print("="*60)
    for idx, (filename, _) in enumerate(configs, 1):
        clean_name = filename.replace('config_', '').replace('.json', '')
        print(f"{idx:2d}) {clean_name}")
    print("="*60)
    
    print("\nWähle Konfiguration(en) zum Anzeigen:")
    print("  Einzeln: z.B. '1' oder '5'")
    print("  Mehrfach: z.B. '1,3,5' oder '1 3 5'")
    
    selection = input("\nAuswahl: ").strip()
    
    selected_indices = []
    for part in selection.replace(',', ' ').split():
        try:
            idx = int(part)
            if 1 <= idx <= len(configs):
                selected_indices.append(idx - 1)
            else:
                logger.warning(f"Index {idx} außerhalb des Bereichs")
        except ValueError:
            logger.warning(f"Ungültige Eingabe: {part}")
    
    if not selected_indices:
        logger.error("Keine gültigen Konfigurationen gewählt!")
        sys.exit(1)
    
    return [configs[i] for i in selected_indices]

def load_config(filepath):
    """Lädt eine Konfiguration"""
    with open(filepath, 'r') as f:
        return json.load(f)

def run_backtest_for_chart(df, config, start_capital=1000):
    """Führt Backtest durch und gibt Trades + Equity Curve zurück"""
    if df.empty or len(df) < 52:
        return [], pd.DataFrame(), {"start": start_capital, "end": start_capital, "pnl_pct": 0}
    
    # Ichimoku Engine vorbereiten
    strategy_params = config.get('strategy', {})
    ichimoku_engine = IchimokuEngine(strategy_params)
    processed_data = ichimoku_engine.process_dataframe(df.copy())
    
    # Indikatoren hinzufügen (ADX, Volume)
    import ta
    processed_data['adx'] = ta.momentum.adx(processed_data['high'], processed_data['low'], 
                                           processed_data['close'], window=14)
    
    current_capital = start_capital
    peak_capital = start_capital
    max_dd = 0.0
    trades = []
    equity_curve = [{'timestamp': processed_data.index[0], 'equity': start_capital, 'drawdown_pct': 0}]
    
    position = None
    risk_params = config.get('risk', {})
    risk_per_trade_pct = risk_params.get('risk_per_trade_pct', 1.0) / 100
    risk_reward_ratio = risk_params.get('risk_reward_ratio', 2.0)
    
    params_for_logic = {"strategy": strategy_params, "risk": risk_params}
    
    for timestamp, candle in processed_data.iterrows():
        if current_capital <= 0:
            break
        
        # Prüfe Exit für offene Position
        if position:
            exit_price = None
            
            if position['side'] == 'long':
                if candle['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif candle['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
            elif position['side'] == 'short':
                if candle['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif candle['low'] <= position['take_profit']:
                    exit_price = position['take_profit']
            
            if exit_price:
                pnl_pct = (exit_price / position['entry_price'] - 1) if position['side'] == 'long' \
                         else (1 - exit_price / position['entry_price'])
                pnl_usd = position['notional'] * pnl_pct
                current_capital += pnl_usd
                
                trades.append({
                    'entry_long' if position['side'] == 'long' else 'entry_short': {
                        'time': position['entry_time'],
                        'price': position['entry_price']
                    },
                    'exit_long' if position['side'] == 'long' else 'exit_short': {
                        'time': timestamp,
                        'price': exit_price
                    },
                    'pnl_pct': pnl_pct * 100,
                    'pnl_usd': pnl_usd
                })
                position = None
        
        # Prüfe Entry Signal
        if not position:
            signal_side, signal_price = get_titan_signal(processed_data.loc[:timestamp], 
                                                        candle, params_for_logic)
            
            if signal_side and signal_price:
                entry_risk_usd = current_capital * risk_per_trade_pct
                atr_val = candle.get('atr', signal_price * 0.02)
                
                if signal_side == 'buy':
                    stop_loss = signal_price - (atr_val * 2)
                    take_profit = signal_price + (atr_val * 2 * risk_reward_ratio)
                    risk_usd = signal_price - stop_loss
                    notional = entry_risk_usd / risk_usd if risk_usd > 0 else current_capital * 0.1
                else:
                    stop_loss = signal_price + (atr_val * 2)
                    take_profit = signal_price - (atr_val * 2 * risk_reward_ratio)
                    risk_usd = stop_loss - signal_price
                    notional = entry_risk_usd / risk_usd if risk_usd > 0 else current_capital * 0.1
                
                position = {
                    'side': 'long' if signal_side == 'buy' else 'short',
                    'entry_price': signal_price,
                    'entry_time': timestamp,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'notional': notional
                }
        
        # Equity Curve updaten
        peak_capital = max(peak_capital, current_capital)
        drawdown = (peak_capital - current_capital) / peak_capital * 100 if peak_capital > 0 else 0
        max_dd = max(max_dd, drawdown)
        
        equity_curve.append({
            'timestamp': timestamp,
            'equity': current_capital,
            'drawdown_pct': drawdown
        })
    
    equity_df = pd.DataFrame(equity_curve)
    stats = {
        'start': start_capital,
        'end': current_capital,
        'pnl_usd': current_capital - start_capital,
        'pnl_pct': (current_capital - start_capital) / start_capital * 100,
        'max_dd': max_dd,
        'trades': len(trades)
    }
    
    return trades, equity_df, stats

def create_interactive_chart(symbol, timeframe, df, trades, equity_df, stats, start_date=None, end_date=None, window=None):
    """Erstellt interaktiven Chart mit Ichimoku + Trades + Equity Curve"""
    
    # Filter auf Fenster
    if window:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=window)
        df = df[df.index >= cutoff_date].copy()
        equity_df = equity_df[pd.to_datetime(equity_df['timestamp']) >= cutoff_date].copy()
    
    # Filter auf Start/End Datum
    if start_date:
        df = df[df.index >= pd.to_datetime(start_date, utc=True)]
        equity_df = equity_df[pd.to_datetime(equity_df['timestamp']) >= pd.to_datetime(start_date, utc=True)]
    if end_date:
        df = df[df.index <= pd.to_datetime(end_date, utc=True)]
        equity_df = equity_df[pd.to_datetime(equity_df['timestamp']) <= pd.to_datetime(end_date, utc=True)]
    
    # Erstelle Subplot mit 2 Zeilen (Chart + Equity Curve)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        row_heights=[0.7, 0.3],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # === HAUPTCHART (Candlestick + Ichimoku) ===
    
    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='OHLC',
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
            showlegend=True
        ),
        row=1, col=1
    )
    
    # === ICHIMOKU INDIKATOREN ===
    
    fig.add_trace(
        go.Scatter(x=df.index, y=df['tenkan_sen'], name='Tenkan-sen',
                   line=dict(color='red', width=2), showlegend=True),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df.index, y=df['kijun_sen'], name='Kijun-sen',
                   line=dict(color='blue', width=2), showlegend=True),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df.index, y=df['senkou_span_a'], name='Senkou Span A',
                   line=dict(color='green', width=1, dash='dash'), showlegend=True),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df.index, y=df['senkou_span_b'], name='Senkou Span B',
                   line=dict(color='orange', width=1, dash='dash'),
                   fill='tonexty', fillcolor='rgba(0,200,0,0.2)', showlegend=True),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=df.index, y=df['chikou_span'], name='Chikou Span',
                   line=dict(color='purple', width=1, dash='dot'), showlegend=True),
        row=1, col=1
    )
    
    # === TRADE SIGNALE ===
    
    entry_long_x, entry_long_y = [], []
    exit_long_x, exit_long_y = [], []
    entry_short_x, entry_short_y = [], []
    exit_short_x, exit_short_y = [], []
    
    for trade in trades:
        if 'entry_long' in trade:
            entry_long_x.append(trade['entry_long']['time'])
            entry_long_y.append(trade['entry_long']['price'])
        if 'exit_long' in trade:
            exit_long_x.append(trade['exit_long']['time'])
            exit_long_y.append(trade['exit_long']['price'])
        if 'entry_short' in trade:
            entry_short_x.append(trade['entry_short']['time'])
            entry_short_y.append(trade['entry_short']['price'])
        if 'exit_short' in trade:
            exit_short_x.append(trade['exit_short']['time'])
            exit_short_y.append(trade['exit_short']['price'])
    
    if entry_long_x:
        fig.add_trace(
            go.Scatter(x=entry_long_x, y=entry_long_y, mode="markers",
                      marker=dict(color="#16a34a", symbol="triangle-up", size=14, 
                                line=dict(width=1.2, color="#0f5132")),
                      name="Entry Long", showlegend=True),
            row=1, col=1
        )
    
    if exit_long_x:
        fig.add_trace(
            go.Scatter(x=exit_long_x, y=exit_long_y, mode="markers",
                      marker=dict(color="#22d3ee", symbol="circle", size=12,
                                line=dict(width=1.1, color="#0e7490")),
                      name="Exit Long", showlegend=True),
            row=1, col=1
        )
    
    if entry_short_x:
        fig.add_trace(
            go.Scatter(x=entry_short_x, y=entry_short_y, mode="markers",
                      marker=dict(color="#f59e0b", symbol="triangle-down", size=14,
                                line=dict(width=1.2, color="#92400e")),
                      name="Entry Short", showlegend=True),
            row=1, col=1
        )
    
    if exit_short_x:
        fig.add_trace(
            go.Scatter(x=exit_short_x, y=exit_short_y, mode="markers",
                      marker=dict(color="#ef4444", symbol="diamond", size=12,
                                line=dict(width=1.1, color="#7f1d1d")),
                      name="Exit Short", showlegend=True),
            row=1, col=1
        )
    
    # === EQUITY CURVE ===
    
    fig.add_trace(
        go.Scatter(x=pd.to_datetime(equity_df['timestamp']), y=equity_df['equity'],
                  name='Equity', line=dict(color='#1f77b4', width=2), showlegend=True),
        row=2, col=1
    )
    
    # === LAYOUT ===
    
    title_str = f"UtBot2 - {symbol} {timeframe} (Ichimoku Cloud)"
    if stats['pnl_pct'] >= 0:
        title_color = "green"
    else:
        title_color = "red"
    
    pnl_text = f"PnL: {stats['pnl_usd']:.2f} USD ({stats['pnl_pct']:.2f}%) | Max DD: {stats['max_dd']:.2f}% | Trades: {stats['trades']}"
    
    fig.update_layout(
        title=f"{title_str}<br><sub>{pnl_text}</sub>",
        height=900,
        hovermode='x unified',
        template='plotly_white',
        dragmode='zoom',
        showlegend=True,
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="left", x=0.01)
    )
    
    fig.update_xaxes(title_text="Zeit", row=2, col=1)
    fig.update_yaxes(title_text="Preis", row=1, col=1)
    fig.update_yaxes(title_text="Eigenkapital", row=2, col=1)
    
    return fig

def main():
    selected_configs = select_configs()
    
    print("\n" + "="*60)
    print("Chart-Optionen:")
    print("="*60)
    
    start_date = input("Startdatum (YYYY-MM-DD) [leer=beliebig]: ").strip() or None
    end_date = input("Enddatum (YYYY-MM-DD) [leer=heute]: ").strip() or None
    start_capital = input("Startkapital (USDT) [Standard: 1000]: ").strip() or "1000"
    window_input = input("Letzten N Tage anzeigen [leer=alle]: ").strip()
    window = int(window_input) if window_input.isdigit() else None
    send_telegram = input("Telegram versenden? (j/n) [Standard: n]: ").strip().lower() in ['j', 'y', 'yes']
    
    try:
        start_capital = float(start_capital)
    except ValueError:
        start_capital = 1000.0
    
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json'), 'r') as f:
            secrets = json.load(f)
    except Exception as e:
        logger.error(f"Fehler beim Laden von secret.json: {e}")
        sys.exit(1)
    
    account = secrets.get('utbot2', [None])[0]
    if not account:
        logger.error("Keine UtBot2-Accountkonfiguration gefunden")
        sys.exit(1)
    
    exchange = Exchange(account)
    telegram_config = secrets.get('telegram', {})
    
    # Generiere Chart für jede gewählte Config
    for filename, filepath in selected_configs:
        try:
            logger.info(f"\nVerarbeite {filename}...")
            
            config = load_config(filepath)
            symbol = config['market']['symbol']
            timeframe = config['market']['timeframe']
            
            logger.info(f"Lade OHLCV-Daten für {symbol} {timeframe}...")
            df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=500)
            
            if df is None or len(df) == 0:
                logger.warning(f"Keine Daten für {symbol} {timeframe}")
                continue
            
            # Ichimoku Indikatoren berechnen
            logger.info("Berechne Ichimoku-Indikatoren...")
            ichimoku_engine = IchimokuEngine(config.get('strategy', {}))
            df = ichimoku_engine.process_dataframe(df)
            
            # ATR hinzufügen
            import ta
            df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
            
            # Backtest durchführen
            logger.info("Führe Backtest durch...")
            trades, equity_df, stats = run_backtest_for_chart(df, config, start_capital)
            
            # Chart erstellen
            logger.info("Erstelle Chart...")
            fig = create_interactive_chart(
                symbol, timeframe, df, trades, equity_df, stats,
                start_date, end_date, window
            )
            
            # Speichern
            safe_name = f"{symbol.replace('/', '_')}_{timeframe}"
            output_file = f"/tmp/utbot2_{safe_name}.html"
            fig.write_html(output_file)
            logger.info(f"✅ Chart gespeichert: {output_file}")
            
            # Telegram versenden
            if send_telegram and telegram_config:
                try:
                    logger.info("Sende Chart via Telegram...")
                    from utbot2.utils.telegram import send_document
                    bot_token = telegram_config.get('bot_token')
                    chat_id = telegram_config.get('chat_id')
                    if bot_token and chat_id:
                        caption = f"UtBot2 Chart: {symbol} {timeframe}\nPnL: {stats['pnl_pct']:.2f}%"
                        send_document(bot_token, chat_id, output_file, caption)
                        logger.info("✅ Chart via Telegram versendet")
                except Exception as e:
                    logger.warning(f"Konnte Chart nicht via Telegram versenden: {e}")
        
        except Exception as e:
            logger.error(f"Fehler bei {filename}: {e}", exc_info=True)
            continue
    
    logger.info("\n✅ Alle Charts generiert!")

if __name__ == '__main__':
    main()
