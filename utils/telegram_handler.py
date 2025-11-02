def format_trade_message(symbol, side, entry_price, sl_price, tp_price, amount, filled):
    """
    Formatiert eine Telegram-Nachricht für Trade-Reporting.
    """
    direction = "LONG 🟢" if side == "buy" else "SHORT 🔴"

    return (
        f"📈 *Neuer Trade eröffnet*\n\n"
        f"Symbol: *{symbol}*\n"
        f"Richtung: *{direction}*\n"
        f"Einstieg: `{entry_price:.4f}`\n"
        f"SL: `{sl_price:.4f}`\n"
        f"TP: `{tp_price:.4f}`\n"
        f"Menge: `{amount:.4f}` (gefüllt: `{filled:.4f}`)\n"
    )
