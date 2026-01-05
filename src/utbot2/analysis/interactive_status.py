#!/usr/bin/env python3
"""
Interactive Charts für UtBot2 - Ichimoku Cloud Strategie
Zeigt Candlestick-Chart mit Ichimoku Indikatoren (Tenkan, Kijun, Kumo)
Nutzt durchnummerierte Konfigurationsdateien zum Auswählen
Basiert auf ltbbot interactive_status.py
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import plotly.graph_objects as go

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from utbot2.utils.exchange import Exchange
from utbot2.strategy.ichimoku_engine import IchimokuEngine

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

def create_interactive_chart(symbol, timeframe, df, start_date, end_date, window=None):
    """Erstellt interaktiven Chart mit Ichimoku Cloud Indikatoren"""
    
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
    
    # Candlestick Chart mit Ichimoku Farben
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
        )
    )
    
    # === ICHIMOKU CLOUD INDIKATOREN ===
    
    # Tenkan-sen (Conversion Line)
    if 'tenkan_sen' in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df['tenkan_sen'], name='Tenkan-sen',
                      line=dict(color='red', width=2), showlegend=True)
        )
    
    # Kijun-sen (Base Line)
    if 'kijun_sen' in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df['kijun_sen'], name='Kijun-sen',
                      line=dict(color='blue', width=2), showlegend=True)
        )
    
    # Senkou Span A (obere Wolke)
    if 'senkou_span_a' in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df['senkou_span_a'], name='Senkou Span A',
                      line=dict(color='green', width=1, dash='dash'), showlegend=True)
        )
    
    # Senkou Span B (untere Wolke mit Fill)
    if 'senkou_span_b' in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df['senkou_span_b'], name='Senkou Span B',
                      line=dict(color='orange', width=1, dash='dash'),
                      fill='tonexty', fillcolor='rgba(0,200,0,0.2)', showlegend=True)
        )
    
    # Chikou Span (Lagging Span)
    if 'chikou_span' in df.columns:
        fig.add_trace(
            go.Scatter(x=df.index, y=df['chikou_span'], name='Chikou Span',
                      line=dict(color='purple', width=1, dash='dot'), showlegend=True)
        )
    
    title = f"{symbol} {timeframe} - UtBot2 (Ichimoku Cloud)"
    fig.update_layout(
        title=title,
        height=600,
        hovermode='x unified',
        template='plotly_white',
        dragmode='zoom',
        xaxis=dict(rangeslider=dict(visible=False), fixedrange=False),
        yaxis=dict(fixedrange=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        showlegend=True
    )
    
    fig.update_yaxes(title_text="Preis")
    fig.update_xaxes(fixedrange=False)
    
    return fig

def main():
    selected_configs = select_configs()
    
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
            
            # Bestimme Ladetarife
            if not start_date:
                start_date_for_load = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
            else:
                start_date_for_load = start_date
            
            if not end_date:
                end_date_for_load = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            else:
                end_date_for_load = end_date
            
            df = exchange.fetch_historical_ohlcv(symbol, timeframe, start_date_for_load, end_date_for_load)
            
            if df is None or len(df) == 0:
                logger.warning(f"Keine Daten für {symbol} {timeframe}")
                continue
            
            # Ichimoku Indikatoren berechnen
            logger.info("Berechne Ichimoku-Indikatoren...")
            ichimoku_engine = IchimokuEngine(config.get('strategy', {}))
            df = ichimoku_engine.process_dataframe(df)
            
            # Chart erstellen
            logger.info("Erstelle Chart...")
            fig = create_interactive_chart(
                symbol,
                timeframe,
                df,
                start_date,
                end_date,
                window
            )
            
            safe_name = f"{symbol.replace('/', '_')}_{timeframe}"
            output_file = f"/tmp/utbot2_{safe_name}.html"
            fig.write_html(output_file)
            logger.info(f"✅ Chart gespeichert: {output_file}")
            
            # Telegram versenden (optional)
            if send_telegram and telegram_config:
                try:
                    logger.info("Sende Chart via Telegram...")
                    from utbot2.utils.telegram import send_document
                    bot_token = telegram_config.get('bot_token')
                    chat_id = telegram_config.get('chat_id')
                    if bot_token and chat_id:
                        send_document(bot_token, chat_id, output_file, caption=f"Chart: {symbol} {timeframe}")
                        logger.info("✅ Chart via Telegram versendet")
                except Exception as e:
                    logger.warning(f"Konnte Chart nicht via Telegram versenden: {e}")
        
        except Exception as e:
            logger.error(f"Fehler bei {filename}: {e}", exc_info=True)
            continue
    
    logger.info("\n✅ Alle Charts generiert!")

if __name__ == '__main__':
    main()
