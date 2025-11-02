import requests
import logging

logger = logging.getLogger('utbot2')

def send_telegram_message(telegram_config, message):
    """
    Sends a formatted message to Telegram using bot token and chat ID from config.
    telegram_config muss sein:
    {
        "bot_token": "...",
        "chat_id": "..."
    }
    """
    bot_token = telegram_config.get("bot_token")
    chat_id = telegram_config.get("chat_id")

    if not bot_token or not chat_id:
        logger.warning("Telegram Bot-Token oder Chat-ID nicht konfiguriert.")
        return

    escape_chars = '_*[]()~`>#+-=|{}.!'
    for char in escape_chars:
        message = message.replace(char, f'\\{char}')

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'MarkdownV2'
    }

    try:
        response = requests.post(api_url, data=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Fehler beim Senden der Telegram-Nachricht: {response.text}")
    except Exception as e:
        logger.error(f"Ausnahme beim Senden der Telegram-Nachricht: {e}")


def format_trade_message(symbol, side, entry_price, sl_price, tp_price, amount, filled):
    direction = "🟢 LONG" if side == "buy" else "🔴 SHORT"

    return (
        f"📈 *Neuer Trade eröffnet*\n\n"
        f"*Symbol:* {symbol}\n"
        f"*Richtung:* {direction}\n"
        f"*Einstieg:* `{entry_price:.4f}`\n"
        f"*Stop-Loss:* `{sl_price:.4f}`\n"
        f"*Take-Profit:* `{tp_price:.4f}`\n"
        f"*Menge:* `{amount:.4f}` (gefüllt: `{filled:.4f}`)\n"
    )
