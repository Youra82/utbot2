# utbot2/utils/guardian.py
import logging
from functools import wraps
import traceback # Hinzugefügt für detailliertere Logs

# Stelle sicher, dass der Importpfad korrekt ist
from utils.telegram_handler import send_telegram_message

def guardian_decorator(func):
    """
    Ein Decorator, der eine Funktion umschließt, um alle unerwarteten
    Ausnahmen abzufangen, sie zu protokollieren und eine Telegram-Warnung zu senden,
    anstatt den Prozess abstürzen zu lassen.
    Angepasst für utbot2.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = None
        telegram_config = {}
        symbol = "Unbekannt"
        timeframe = "N/A"

        # Finde Logger, Telegram-Config und Symbol/Timeframe in den Argumenten
        # (Angepasst an die Struktur von utbot2's main loop)
        try:
            # Erwartete Argumente für die dekorierte Funktion in main.py:
            # target (0), strategy_cfg (1), exchange (2), gemini_model (3), secrets['telegram'] (4), logger (5)
            target = args[0]
            telegram_config = args[4]
            
            # --- KORREKTUR: Index von 6 auf 5 geändert ---
            logger = args[5] 
            # --- ENDE KORREKTUR ---

            symbol = target.get('symbol', symbol)
            timeframe = target.get('timeframe', timeframe)
        except IndexError:
            # Fallback, falls Argumente anders übergeben werden
            for arg in args:
                if isinstance(arg, logging.Logger): logger = arg
                if isinstance(arg, dict) and 'bot_token' in arg: telegram_config = arg
                if isinstance(arg, dict) and 'symbol' in arg:
                    symbol = arg.get('symbol', symbol)
                    timeframe = arg.get('timeframe', timeframe)

        if not logger:
            logger = logging.getLogger("guardian_fallback")
            logger.setLevel(logging.ERROR)
            if not logger.handlers: logger.addHandler(logging.StreamHandler())

        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_message = f"Ein kritischer Systemfehler ist im Guardian für {symbol} ({timeframe}) aufgetreten."
            detailed_error = f"Fehlerdetails: {e.__class__.__name__}: {e}\n{traceback.format_exc()}" # Mehr Details

            logger.critical("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            logger.critical("!!! KRITISCHER SYSTEMFEHLER IM GUARDIAN !!!")
            logger.critical(f"!!! Strategie: {symbol} ({timeframe})")
            logger.critical(f"!!! Fehler: {detailed_error}") # Detaillierte Ausgabe
            logger.critical("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

            try:
                telegram_message = f"🚨 *Kritischer Systemfehler* im Guardian für *{symbol} ({timeframe})*.\n\n`{e.__class__.__name__}: {str(e)[:100]}`"
                send_telegram_message(
                    telegram_config.get('bot_token'),
                    telegram_config.get('chat_id'),
                    telegram_message
                )
            except Exception as tel_e:
                logger.error(f"Konnte keine Telegram-Warnung senden: {tel_e}")
    return wrapper
