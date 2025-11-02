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
        return toml.load(open(p, 'r', encoding='utf-8'))
    return json.load(open(p, 'r', encoding='utf-8'))


def setup_logging(symbol, timeframe):
    logger = logging.getLogger(f'utbot2_{symbol}_{timeframe}')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s UTC - %(levelname)s: %(message)s'))
        logger.addHandler(handler)
    return logger


class MockGeminiResponse:
    def __init__(self, text):
        self.text = text
        self.parts = [True]


class MockGeminiModel:
    def set_next_response(self, action, sl, tp):
        self.response = json.dumps({"aktion": action, "stop_loss": sl, "take_profit": tp})

    def generate_content(self, *_, **__):
        return MockGeminiResponse(self.response)


# ✅ Richtige Reihenfolge: Fixture außen, Patch innen
@pytest.fixture(scope="module")
@patch('utils.exchange_handler.ExchangeHandler.fetch_ohlcv', MagicMock(return_value=pd.DataFrame(
    {'open': 2.4, 'high': 2.6, 'low': 2.3, 'close': 2.5, 'volume': 1000},
    index=pd.to_datetime(pd.RangeIndex(start=1, stop=101), unit='s', utc=True)
)))
def workflow_context():

    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    config_path = os.path.join(PROJECT_ROOT, 'config.toml')

    if not os.path.exists(secret_path):
        pytest.skip("secret.json fehlt → Test übersprungen")

    secrets = load_config(secret_path)
    config = load_config(config_path)

    bitget = secrets.get('bitget')
    if not bitget:
        pytest.skip("Bitget API Keys fehlen → Test übersprungen")

    target = next((t for t in config['targets'] if t['enabled']), None)
    if not target:
        pytest.skip("Kein aktives Target in config → Test übersprungen")

    exchange = ExchangeHandler()
    exchange.session = ccxt.bitget({
        'apiKey': bitget['apiKey'],
        'secret': bitget['secret'],
        'password': bitget['password'],
        'options': {'defaultType': 'swap'},
    })
    exchange.session.load_markets()

    logger = setup_logging(target['symbol'], target['timeframe'])

    gemini = MockGeminiModel()

    yield exchange, gemini, config, target, secrets.get('telegram', {}), logger

    exchange.cleanup_all_open_orders(target['symbol'])


def test_full_utbot2_workflow_on_bitget(workflow_context):
    exchange, gemini, config, target, telegram_cfg, logger = workflow_context
    symbol = target['symbol']

    ticker = exchange.fetch_ticker(symbol)
    price = ticker['last']

    gemini.set_next_response("KAUFEN", price * 0.98, price * 1.04)

    balance = exchange.fetch_balance_usdt()
    if balance < 1.0:
        pytest.skip("Zu wenig Balance für Test")

    target['risk']['portfolio_fraction_pct'] = 100
    target['risk']['max_leverage'] = 100

    run_strategy_cycle(target, config['strategy'], exchange, gemini, telegram_cfg, logger)
    time.sleep(4)

    positions = exchange.fetch_open_positions(symbol)
    assert len(positions) == 1
    assert positions[0]['side'] == "long"

    triggers = exchange.fetch_open_trigger_orders(symbol)
    assert len(triggers) == 2

