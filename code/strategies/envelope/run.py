#!/usr/bin/env python3
import json
import time
import logging
from datetime import datetime, timezone

# Strategieparameter mit Beschreibung (komplett)
STRATEGIEPARAMETER = {
    "ema_fast": {
        "wert": 9,
        "beschreibung": "Schneller EMA für Signal-Generierung"
    },
    "ema_slow": {
        "wert": 21,
        "beschreibung": "Langsamer EMA für Trendbestimmung"
    },
    "min_trade_size": {
        "wert": 0.001,
        "beschreibung": "Minimale Positionsgröße in BTC für einen Trade"
    },
    "max_risk_per_trade": {
        "wert": 0.02,
        "beschreibung": "Maximaler Risikoprozentanteil des Kontostands pro Trade"
    },
    # Weitere Parameter hier ergänzen...
}

LOG_FILE = "/home/ubuntu/utbot2/logs/envelope.log"
TRACKER_FILE = "/home/ubuntu/utbot2/code/strategies/envelope/tracker_BTC-USDT-USDT.json"

# Logging konfigurieren
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s %(message)s')

def log_strategieparameter():
    """Loggt die aktuellen Strategieparameter mit Beschreibung."""
    param_lines = []
    for key, val in STRATEGIEPARAMETER.items():
        param_lines.append(f"{key}: {val['wert']} ({val['beschreibung']})")
    logging.info("Strategieparameter: " + " | ".join(param_lines))

def lade_tracker():
    """Lädt den Tracker (z.B. aktueller Status) aus JSON."""
    try:
        with open(TRACKER_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Fehler beim Laden des Tracker-Files: {e}")
        return {}

def speichere_tracker(tracker):
    """Speichert den Tracker als JSON."""
    try:
        with open(TRACKER_FILE, "w") as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logging.error(f"Fehler beim Speichern des Tracker-Files: {e}")

def ermittle_signal(marktdaten):
    """
    Kompromisslose Signalgenerierung nach Vorgabe:
    - Beispiel: EMA-Schnittpunkt (Dummy-Code hier, ersetze mit deinem Originalalgorithmus)
    """
    # Platzhalter: immer Kauf-Signal wenn fast EMA > slow EMA, sonst kein Signal
    ema_fast = marktdaten.get("ema_fast", 0)
    ema_slow = marktdaten.get("ema_slow", 0)

    if ema_fast > ema_slow:
        return "Kauf"
    elif ema_fast < ema_slow:
        return "Verkauf"
    else:
        return None

def pruefe_handelsbedingungen(signal, kontostand, min_trade_size):
    """
    Prüft alle Handelsbedingungen detailliert und liefert Grund, warum Trade
    nicht möglich ist, falls zutreffend.
    """
    grunde = []

    if signal is None:
        grunde.append("Kein gültiges Handelssignal vorhanden")
    if kontostand <= 0:
        grunde.append("Kontostand ist 0 oder negativ")
    if kontostand < min_trade_size:
        grunde.append(f"Kontostand ({kontostand:.4f} USDT) zu niedrig für Mindest-Tradegröße ({min_trade_size} BTC)")
    
    # Beispiel: hier könnten weitere Bedingungen geprüft werden:
    # - Positionsgröße zu klein
    # - Status im Tracker ungünstig
    # - Signal abgelaufen
    # - usw.

    if grunde:
        return False, grunde
    return True, []

def berechne_positionsgroesse(kontostand, risiko_prozent, min_trade_size):
    """
    Berechnet Positionsgröße basierend auf Risiko und Kontostand.
    Falls Positionsgröße unter min_trade_size, wird Hebel vorgeschlagen.
    """
    maximale_positionsgroesse = kontostand * risiko_prozent
    if maximale_positionsgroesse < min_trade_size:
        hebel = min_trade_size / maximale_positionsgroesse if maximale_positionsgroesse > 0 else float('inf')
        return maximale_positionsgroesse, hebel
    else:
        return min_trade_size, 1

def fuehre_trade_aus(signal, positionsgroesse):
    """
    Dummy-Funktion: Hier wird der Trade gestartet.
    In Wirklichkeit z.B. API-Call an Exchange.
    """
    logging.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTC-USDT",
        "signal": signal,
        "decision": "Trade ausgeführt",
        "details": f"Positionsgröße {positionsgroesse:.6f} BTC"
    }))

def log_handelsentscheidung(timestamp, symbol, signal, decision, details):
    """Schreibt eine strukturierte Log-Zeile mit Handelsentscheidung."""
    log_entry = json.dumps({
        "timestamp": timestamp,
        "symbol": symbol,
        "signal": signal,
        "decision": decision,
        "details": details
    })
    logging.info(f"TRADE_DECISION: {log_entry}")

def main_loop():
    log_strategieparameter()
    tracker = lade_tracker()

    # Beispiel für Kontostand - in Realität aus API oder Tracker laden
    kontostand = 1000.00  # USDT, dummy-Wert, bitte anpassen
    risiko_prozent = STRATEGIEPARAMETER["max_risk_per_trade"]["wert"]
    min_trade_size = STRATEGIEPARAMETER["min_trade_size"]["wert"]

    # Dummy-Marktdaten (ersetze mit Echt-Datenquelle)
    marktdaten = {
        "ema_fast": 10,
        "ema_slow": 8
    }

    signal = ermittle_signal(marktdaten)
    timestamp = datetime.now(timezone.utc).isoformat()
    symbol = "BTC-USDT"

    # Signal-Log
    logging.info(f"Gefundene Signale: {signal if signal else 'Kein Signal'}")

    # Prüfe Handelsbedingungen
    erlaubnis, grunde = pruefe_handelsbedingungen(signal, kontostand, min_trade_size)

    if not erlaubnis:
        details = "; ".join(grunde)
        log_handelsentscheidung(timestamp, symbol, signal if signal else "-", "Trade abgelehnt", details)

        # Wenn Kontostand zu niedrig
        if any("Kontostand" in g for g in grunde):
            maximale_positionsgroesse, hebel = berechne_positionsgroesse(kontostand, risiko_prozent, min_trade_size)
            info = f"Minimale Positionsgröße: {min_trade_size} BTC, Aktuell mögliche Größe: {maximale_positionsgroesse:.6f} BTC"
            if hebel > 1:
                info += f"; Empfohlener Hebel: {hebel:.2f}x"
            logging.info(f"Handelsgröße-Info: {info}")
        return

    # Berechne Positionsgröße
    positionsgroesse, hebel = berechne_positionsgroesse(kontostand, risiko_prozent, min_trade_size)
    if hebel > 1:
        logging.info(f"Handelsgröße kleiner als Mindestgröße, empfohlener Hebel: {hebel:.2f}x")

    fuehre_trade_aus(signal, positionsgroesse)
    log_handelsentscheidung(timestamp, symbol, signal, "Trade ausgeführt", f"Positionsgröße {positionsgroesse:.6f} BTC")

    # Tracker ggf. aktualisieren
    # (z.B. Position als offen markieren, Zeitstempel setzen)
    tracker["letzte_position"] = {
        "zeit": timestamp,
        "signal": signal,
        "positionsgroesse": positionsgroesse
    }
    speichere_tracker(tracker)

if __name__ == "__main__":
    while True:
        main_loop()
        time.sleep(60)  # alle 60 Sekunden prüfen, anpassen nach Bedarf
