#!/usr/bin/env python3
"""
Interactive Charts für UtBot2 - Ichimoku Cloud Strategie
Zeigt Candlestick-Chart mit Ichimoku Indikatoren (Tenkan, Kijun, Kumo)
Nutzt durchnummerierte Konfigurationsdateien zum Auswählen
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import ta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

def setup_logging():
    logger = logging.getLogger('interactive_status')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(ch)
    return logger

logger = setup_logging()

def detect_bot_name():
    """Erkennt welcher Bot am laufen ist basierend auf PWD"""
    cwd = os.getcwd()
    for bot_name in ['pbot', 'stbot', 'utbot2', 'titanbot']:
        if bot_name in cwd:
            return bot_name
    return 'pbot'  # Default

BOT_NAME = detect_bot_name()

def get_config_files():
    """Sucht alle Konfigurationsdateien auf"""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', BOT_NAME, 'strategy', 'configs')
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
        # Extrahiere Symbol/Timeframe aus Dateiname
        clean_name = filename.replace('config_', '').replace('.json', '')
        print(f"{idx:2d}) {clean_name}")
    print("="*60)
    
    print("\nWähle Konfiguration(en) zum Anzeigen:")
    print("  Einzeln: z.B. '1' oder '5'")
    print("  Mehrfach: z.B. '1,3,5' oder '1 3 5'")
    
    selection = input("\nAuswahl: ").strip()
    
    # Parse Eingabe
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

def add_ichimoku_indicators(df):
    """Fügt Ichimoku Cloud Indikatoren hinzu"""
    # Ichimoku Parameter (Standard für Krypto)
    tenkan_period = 9
    kijun_period = 26
    senkou_span_b_period = 52
    displacement = 26
    
    # Hilfsfunktion: Donchian Channel
    def donchian(high, low, window):
        return (high.rolling(window).max() + low.rolling(window).min()) / 2
    
    # Ichimoku Linien berechnen
    df['tenkan_sen'] = donchian(df['high'], df['low'], tenkan_period)
    df['kijun_sen'] = donchian(df['high'], df['low'], kijun_period)
    
    # Senkou Spans (verschoben)
    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(displacement)
    df['senkou_span_b'] = donchian(df['high'], df['low'], senkou_span_b_period).shift(displacement)
    
    # Chikou Span (verzögert)
    df['chikou_span'] = df['close'].shift(-displacement)
    
    return df

def create_interactive_chart(symbol, timeframe, df, trades, start_date, end_date, window=None):
    """Erstellt interaktiven Chart mit Ichimoku Cloud Indikatoren und Trades"""
    
    # Filter auf Fenster
    if window:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=window)
        df = df[df.index >= cutoff_date].copy()
    
    # Filter auf Start/End Datum
    if start_date:
        df = df[df.index >= pd.to_datetime(start_date, utc=True)]
    if end_date:
        df = df[df.index <= pd.to_datetime(end_date, utc=True)]
    
    fig = go.Figure()
    
    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='OHLC',
            showlegend=True
        )
    )
    
    # === ICHIMOKU CLOUD INDIKATOREN ===
    
    # Tenkan-sen (Conversion Line) - schnelle Linie
    fig.add_trace(
        go.Scatter(x=df.index, y=df['tenkan_sen'], name='Tenkan-sen', 
                   line=dict(color='red', width=2))
    )
    
    # Kijun-sen (Base Line) - langsame Linie
    fig.add_trace(
        go.Scatter(x=df.index, y=df['kijun_sen'], name='Kijun-sen', 
                   line=dict(color='blue', width=2))
    )
    
    # Senkou Span A (Leading Span A) - obere Wolke
    fig.add_trace(
        go.Scatter(x=df.index, y=df['senkou_span_a'], name='Senkou Span A',
                   line=dict(color='green', width=1, dash='dash'),
                   fill=None)
    )
    
    # Senkou Span B (Leading Span B) - untere Wolke
    fig.add_trace(
        go.Scatter(x=df.index, y=df['senkou_span_b'], name='Senkou Span B',
                   line=dict(color='orange', width=1, dash='dash'),
                   fill='tonexty', fillcolor='rgba(0,200,0,0.2)')
    )
    
    # Chikou Span (Lagging Span) - verzögerte Linie
    fig.add_trace(
        go.Scatter(x=df.index, y=df['chikou_span'], name='Chikou Span',
                   line=dict(color='purple', width=1, dash='dot'))
    )
    
    # Trade Marker
    for trade in trades:
        entry_time = trade['entry_time']
        entry_price = trade['entry_price']
        exit_time = trade['exit_time']
        exit_price = trade['exit_price']
        profit = trade['profit']
        
        color = 'green' if profit > 0 else 'red'
        
        # Entry
        fig.add_trace(
            go.Scatter(
                x=[entry_time],
                y=[entry_price],
                mode='markers',
                marker=dict(size=10, color='green', symbol='triangle-up'),
                name=f'Entry ({entry_price:.2f})',
                showlegend=False
            )
        )
        
        # Exit
        fig.add_trace(
            go.Scatter(
                x=[exit_time],
                y=[exit_price],
                mode='markers',
                marker=dict(size=10, color=color, symbol='triangle-down'),
                name=f'Exit ({exit_price:.2f})',
                showlegend=False
            )
        )
        
        # Verbindungslinie
        fig.add_trace(
            go.Scatter(
                x=[entry_time, exit_time],
                y=[entry_price, exit_price],
                mode='lines',
                line=dict(color=color, width=1, dash='dash'),
                showlegend=False
            )
        )
    
    bot_display = BOT_NAME.upper()
    title = f"{symbol} {timeframe} - {bot_display} (Ichimoku Cloud Strategy)"
    fig.update_layout(
        title=title,
        height=800,
        hovermode='x unified',
        template='plotly_dark'
    )
    
    fig.update_yaxes(title_text="Price")
    fig.update_xaxes(title_text="Time")
    
    return fig

def main():
    # Wähle Konfigurationsdateien
    selected_configs = select_configs()
    
    # Parameter für Chart-Generierung
    print("\n" + "="*60)
    print("Chart-Optionen:")
    print("="*60)
    
    start_date = input("Startdatum (YYYY-MM-DD) [leer=beliebig]: ").strip() or None
    end_date = input("Enddatum (YYYY-MM-DD) [leer=heute]: ").strip() or None
    window_input = input("Letzten N Tage anzeigen [leer=alle]: ").strip()
    window = int(window_input) if window_input.isdigit() else None
    send_telegram = input("Telegram versenden? (j/n) [Standard: n]: ").strip().lower() in ['j', 'y', 'yes']
    
    try:
        with open(os.path.join(PROJECT_ROOT, 'secret.json'), 'r') as f:
            secrets = json.load(f)
    except Exception as e:
        logger.error(f"Fehler beim Laden von secret.json: {e}")
        sys.exit(1)
    
    account = secrets.get(BOT_NAME, [None])[0]
    if not account:
        logger.error(f"Keine {BOT_NAME.upper()}-Accountkonfiguration gefunden")
        sys.exit(1)
    
    # Import der passenden Exchange-Klasse
    module = __import__(f'{BOT_NAME}.utils.exchange', fromlist=['Exchange'])
    Exchange = module.Exchange
    
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
            
            logger.info("Berechne Indikatoren...")
            df = add_ichimoku_indicators(df)
            
            # Erstelle Chart
            logger.info("Erstelle Chart...")
            fig = create_interactive_chart(
                symbol,
                timeframe,
                df,
                [],  # Keine Trades für diese vereinachte Version
                start_date,
                end_date,
                window
            )
            
            # Speichere HTML
            safe_name = f"{symbol.replace('/', '_')}_{timeframe}"
            output_file = f"/tmp/{BOT_NAME}_{safe_name}.html"
            fig.write_html(output_file)
            logger.info(f"✅ Chart gespeichert: {output_file}")
            
            # Telegram versenden (optional)
            if send_telegram and telegram_config:
                try:
                    logger.info(f"Sende Chart via Telegram...")
                    telegram_module = __import__(f'{BOT_NAME}.utils.telegram', fromlist=['send_document'])
                    send_document = telegram_module.send_document
                    bot_token = telegram_config.get('bot_token')
                    chat_id = telegram_config.get('chat_id')
                    if bot_token and chat_id:
                        send_document(bot_token, chat_id, output_file, caption=f"Chart: {symbol} {timeframe}")
                except Exception as e:
                    logger.warning(f"Konnte Chart nicht via Telegram versenden: {e}")
        
        except Exception as e:
            logger.error(f"Fehler bei {filename}: {e}", exc_info=False)
            continue
    
    logger.info("\n✅ Alle Charts generiert!")

if __name__ == '__main__':
    main()
