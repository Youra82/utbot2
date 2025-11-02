# tests/test_workflow.py (VOLLSTÄNDIG KORRIGIERT)
import pytest
import os
import sys
import json
import logging
import time
from pathlib import Path
import ccxt
import pandas as pd
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))
sys.path.append(PROJECT_ROOT)

from utils.exchange_handler import ExchangeHandler
from main import run_strategy_cycle


def load_config(file_path):
    p = Path(file_path)
    if p.suffix == '.toml':
        import toml
        with open(p, 'r', encoding='utf-8') as f:
            return toml.load(f)
    elif p.suffix == '.json':
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    raise ValueError(f"Unknown config format: {file_path}")


def setup_logging(symbol, timeframe):
    logger = logging.getLogger(f'utbot2_{symbol.replace("/", "").replace(":", "")}_{timeframe}')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s UTC - %(levelname)s: [%(name)s] %(message)s', datefmt='%H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


class MockGeminiResponse:
    def __init__(self, text):
        self.text = text
        self.parts = [True] if text else []


class MockGeminiModel:
    def __init__(self):
        self.response_json = {"aktion": "KAUFEN", "stop_loss": 0, "take_profit": 0}

    def set_next_response(self, action="KAUFEN", sl=None, tp=None):
        self.response_json = {"aktion": action, "stop_loss": sl, "take_profit": tp}

    def generate_content(self, prompt, **_):
        current_price = 2.50
        try:
            p = str(prompt)
            if "aktueller_preis=" in p:
                current_price = float(p.split("aktueller_preis=")[1].split(",")[0].strip().strip("'\""))
        except:
            pass

        self.set_next_response(sl=current_price * 0.98, tp=current_price * 1.04)
        return MockGeminiResponse(json.dumps(self.response_json))


# ✅ Fixture korrekt benannt (kein 'test_' prefix!)
@patch('utils.exchange_handler.ExchangeHandler.fetch_ohlcv', MagicMock(return_value=pd.DataFrame(
    {'open': 2.4, 'high': 2.6, 'low': 2.3, 'close': 2.5, 'volume': 1000},
    index=pd.to_datetime(pd.RangeIndex(start=1, stop=101), unit='s', utc=True)
).iloc[:100]))
@pytest.fixture(scope="module")
def workflow_context():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    config_path = os.path.join(PROJECT_ROOT, 'config.toml')

    if not os.path.exists(secret_path):
        pytest.skip("secret.json fehlt → Echtbetriebstest wird übersprungen")

    secrets = load_config(secret_path)
    config = load_config(config_path)

    bitget = secrets.get('bitget')
    if not bitget:
        pytest.skip("Bitget API Keys fehlen → Test übersprungen")

    target = next((t for t in config['targets'] if t['enabled']), None)
    if not target:
        pytest.skip("Kein aktives Target für Test gefunden")

    symbol = target['symbol']
    timeframe = target['timeframe']

    exchange = ExchangeHandler()
    logger = setup_logging(symbol, timeframe + "_test")

    exchange.session = ccxt.bitget({
        'apiKey': bitget['apiKey'],
        'secret': bitget['secret'],
        'password': bitget['password'],
        'options': {'defaultType': 'swap'},
    })
    exchange.session.load_markets()

    mock_gemini = MockGeminiModel()

    yield exchange, mock_gemini, config, target, secrets.get('telegram', {}), logger

    exchange.cleanup_all_open_orders(symbol)


def test_full_utbot2_workflow_on_bitget(workflow_context):
    exchange, mock_gemini, config, target, telegram_cfg, logger = workflow_context
    symbol = target['symbol']

    ticker = exchange.fetch_ticker(symbol)
    current_price = ticker['last']
    mock_gemini.set_next_response("KAUFEN", current_price * 0.98, current_price * 1.04)

    balance = exchange.fetch_balance_usdt()
    if balance < 1.0:
        pytest.skip(f"Zu wenig Testguthaben ({balance:.2f} USDT) → Test übersprungen")

    target['risk']['portfolio_fraction_pct'] = 100
    target['risk']['max_leverage'] = 100

    run_strategy_cycle(target, config['strategy'], exchange, mock_gemini, telegram_cfg, logger)
    time.sleep(4)

    positions = exchange.fetch_open_positions(symbol)
    assert len(positions) == 1
    assert positions[0]['side'] == 'long'

    trigger_orders = exchange.fetch_open_trigger_orders(symbol)
    assert len(trigger_orders) == 2
