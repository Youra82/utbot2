# code/utilities/notifications.py
import requests
import logging

def send_telegram_message(config, message):
    """
    Sendet eine Nachricht an den in der Konfiguration angegebenen Telegram-Chat.
    """
    token = config.get("bot_token")
    chat_id = config.get("chat_id")

    if not token or not chat_id:
        logging.warning("Telegram-Zugangsdaten (bot_token, chat_id) in secret.json nicht gefunden. Keine Benachrichtigung gesendet.")
        return

    # Telegram's MarkdownV2 erfordert das Escapen von Sonderzeichen
    escape_chars = '_*[]()~`>#+-=|{}.!'
    # Ersetze nur, wenn das Zeichen nicht bereits escaped ist
    for char in escape_chars:
        message = message.replace(f'\\{char}', char).replace(char, f'\\{char}')

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logging.info("Telegram-Benachrichtigung erfolgreich gesendet.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Fehler beim Senden der Telegram-Nachricht: {e}")
