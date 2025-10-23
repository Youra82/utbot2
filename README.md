# utbot2

Ein vollautomatischer Trading-Bot für Krypto-Futures auf der Bitget-Börse, der **Generative KI (Google Gemini)** nutzt, um Handelsentscheidungen zu treffen.

Dieses System wurde für den Betrieb auf einem Ubuntu-Server entwickelt und führt Trades basierend auf einer zentralen Konfigurationsdatei aus, die eine flexible Steuerung mehrerer Handelspaare und Strategie-Modi erlaubt.

## Kernstrategie (Generative KI-Analyse)

Der Bot implementiert eine KI-gestützte Strategie, die darauf abzielt, die kontextbezogene Mustererkennung eines großen Sprachmodells (LLM) zu nutzen.

**Handelsthese:** Ein großes Sprachmodell (LLM) wie Google Gemini kann die Fähigkeit menschlicher Analysten simulieren, wiederkehrende Muster in Märkten zu erkennen. Durch die Analyse von Preisdaten und technischen Indikatoren in einem vordefinierten, kontextbezogenen Rahmen (z.B. "Swing-Trading") kann es plausible, kurzfristige Handelsentscheidungen generieren, inklusive konkreter Ausstiegsziele.

**Signale:**

  * **Indikator-Analyse:** Vor jeder Entscheidung berechnet der Bot eine Reihe von Schlüsselindikatoren, darunter Momentum (**StochRSI**), Trend/Signal (**MACD**) und Volatilität (**ATR**).
  * **KI-Anfrage (Prompt):** Der Bot erstellt eine detaillierte, kontextbezogene Anfrage für die KI. Diese enthält den gewählten Trading-Stil (z.B. "Swing-Trader"), eine Zusammenfassung der aktuellen Indikatorwerte und die rohen Kerzendaten der letzten Wochen.
  * **Einstieg:** Ein Trade wird nur dann initiiert, wenn die KI in ihrer Antwort eine klare Aktion (`"aktion": "KAUFEN"` oder `"aktion": "VERKAUFEN"`) zurückgibt.

**Ausstieg & Risikomanagement:**

  * **KI-definierte Ziele:** Sowohl der **Stop-Loss** als auch der **Take-Profit** werden direkt von der KI in ihrer JSON-Antwort vorgegeben und vom Bot übernommen.
  * **Dynamische Positionsgröße & Hebel:** Die Positionsgröße wird für jeden Trade dynamisch berechnet, um ein festes prozentuales Risiko des Kapitals zu gewährleisten. Der Hebel wird automatisch basierend auf der Volatilität (ATR) und dem von der KI vorgegebenen Stop-Loss-Abstand angepasst, um das Risiko präzise zu steuern.
  * **Trade-Überwachung:** Der Bot verfügt über ein "Gedächtnis" (`open_trades.json`), um eröffnete Positionen zu verwalten. Er erkennt automatisch, wenn ein Trade durch Stop-Loss oder Take-Profit geschlossen wurde und sendet eine entsprechende Erfolgs- oder Verlust-Benachrichtigung.

## Arbeitsablauf in 2 Phasen

1.  **Phase 1: Strategie KONFIGURIEREN (Manuelle Einrichtung)**
    Du definierst deine gesamte Handelsstrategie durch Bearbeiten der zentralen `config.toml`-Datei. Hier legst du fest, welche Coins gehandelt werden sollen, welchen Trading-Stil die KI anwenden soll (`swing`, `daytrade`, `scalp`) und wie dein Risikomanagement für jeden Coin aussieht.

2.  **Phase 2: Strategie AUSFÜHREN (Live-Handel)**
    Ein Cronjob startet periodisch das `run.sh`-Skript. Der Bot liest die `config.toml`, durchläuft die Liste der aktiven Coins und führt für jeden eine der folgenden Aktionen aus:

      * **Wenn kein Trade offen ist:** Er analysiert den Markt und fragt die KI nach einer neuen Handelsentscheidung.
      * **Wenn ein Trade offen ist:** Er überwacht den Status des Trades und meldet, falls dieser durch SL/TP geschlossen wurde.

## Installation & Einrichtung 🚀

Führe die folgenden Schritte auf einem frischen Ubuntu-Server (empfohlen: 22.04 LTS) aus.

#### 1\. Projekt klonen

Ersetze `DEIN_GITHUB_USERNAME` mit deinem tatsächlichen Benutzernamen.

```bash
git clone https://github.com/Youra82/utbot2.git
```

#### 2\. Installations-Skript ausführen

```bash
cd utbot2
chmod +x install.sh
bash install.sh
```

#### 3\. API-Schlüssel eintragen

Bearbeite die `secret.json`-Datei mit deinen API-Schlüsseln für Bitget, Telegram und Google.

```bash
nano secret.json
```

Speichere mit `Strg + X`, dann `Y`, dann `Enter`.

## Live-Betrieb & Automatisierung

#### 1\. Strategie in `config.toml` festlegen

Dies ist die **einzige Datei**, die du für die Steuerung des Bots bearbeiten musst.

```bash
nano config.toml
```

Passe die globalen Einstellungen und die `[[targets]]`-Blöcke nach deinen Wünschen an.

#### 2\. Automatisierung per Cronjob einrichten

Richte einen automatischen Prozess für den Live-Handel ein.

```bash
# Mache das Start-Skript zuerst ausführbar (einmalig)
chmod +x run.sh
# manuell starten:
bash run.sh

# Öffne den Cronjob-Editor
crontab -e
```

Füge die folgende Zeile am Ende der Datei ein. Sie startet den Bot alle 15 Minuten.

```
*/15 * * * * flock -n /pfad/zu/deinem/utbot2/utbot2.lock cd /pfad/zu/deinem/utbot2 && bash run.sh >> /pfad/zu/deinem/utbot2/logs/cron.log 2>&1
```

*(**Wichtig:** Ersetze `/pfad/zu/deinem/utbot2` durch den tatsächlichen, vollständigen Pfad zu deinem Projektordner, z.B. `/home/ubuntu/utbot2`.)*

## Verwaltung ⚙️

#### Bot aktualisieren 🔄

Um den Code des Bots auf den neuesten Stand zu bringen, ohne deine `secret.json` zu überschreiben, kannst du das mitgelieferte Update-Skript verwenden.

```bash
# 1. Update-Skript ausführbar machen (einmalig)
chmod +x update.sh

# 2. Update ausführen
bash update.sh
```

#### Logs überwachen

Die Ausgaben des Bots werden in die Datei `logs/cron.log` geschrieben.
**Log-Datei in Echtzeit ansehen:**

```bash
tail -f logs/cron.log
```

*(`Strg + C` zum Beenden)*

Die Wahl des richtigen Timeframes hängt direkt von deinem Trading-Stil ab. Hier ist eine Übersicht der gängigsten Kombinationen.

---
## ## Timeframes nach Trading-Stil

Die Grundregel lautet: Je kürzer du einen Trade halten möchtest, desto kleiner sollte dein Timeframe sein.

| Trading-Stil | Typische Timeframes | Zweck / Haltedauer |
| :--- | :--- | :--- |
| **Swing-Trading** | **4h, 1D** (4-Stunden, 1-Tag) | Große Marktschwankungen über **Tage bis Wochen** erfassen. |
| **Day-Trading** | **15m, 1h** (15-Minuten, 1-Stunde) | Trades innerhalb **desselben Tages** eröffnen und schließen. |
| **Scalping** | **1m, 5m** (1-Minute, 5-Minuten) | Viele kleine Gewinne aus minimalen Preisbewegungen erzielen; Haltedauer von **Sekunden bis Minuten**. |



Dein Bot ist aktuell im **Swing-Modus** konfiguriert, weshalb Timeframes wie **4h** oder **1D** am besten zu dieser Einstellung passen.

Komplette Projektstruktur anzeigen:

```bash
chmod +x show_status.sh
```

```bash
bash ./show_status.sh
```
-----
## Qualitätssicherung & Tests 🛡️

Um sicherzustellen, dass alle Kernfunktionen des Bots nach jeder Code-Änderung wie erwartet funktionieren und keine alten Fehler ("Regressionen") wieder auftreten, verfügt das Projekt über ein automatisiertes Test-System.

Dieses "Sicherheitsnetz" prüft zwei Ebenen:

1.  **Struktur-Tests:** Überprüfen, ob alle kritischen Funktionen und Code-Teile vorhanden sind.
2.  **Workflow-Tests:** Führen einen kompletten Live-Zyklus auf der Bitget-API durch (Aufräumen, Order platzieren mit korrekten Einstellungen, SL/TP setzen, Position schließen), um die korrekte Interaktion mit der Börse zu verifizieren.

#### Das Test-System ausführen

Der einfachste Weg, alle Tests zu starten, ist das dafür vorgesehene Skript. Dieser Befehl sollte **nach jeder Code-Änderung** (z.B. nach einem `bash ./update.sh`) ausgeführt werden, um die Stabilität und korrekte Funktion des Bots zu garantieren.

```bash
bash ./run_tests.sh
```

  * **Erfolgreiches Ergebnis:** Alle Tests werden als `PASSED` (grün) markiert. Das bedeutet, alle geprüften Kernfunktionen arbeiten wie erwartet.
  * **Fehlerhaftes Ergebnis:** Mindestens ein Test wird als `FAILED` (rot) markiert. Die Ausgabe gibt einen detaillierten Hinweis darauf, welche Funktion nicht mehr wie erwartet funktioniert. In diesem Fall sollte der Bot nicht im Live-Betrieb eingesetzt werden, bis der Fehler behoben ist.

-----

### ✅ Requirements

  - Python 3.10+
  - Siehe `requirements.txt` für die spezifischen Python-Pakete.

### 📃 License

Dieses Projekt ist unter der [GNU General Public License](https://www.google.com/search?q=LICENSE) lizenziert.

### ⚠️ Disclaimer

Dieses Material dient ausschließlich zu Bildungs- und Unterhaltungszwecken. Es handelt sich nicht um eine Finanzberatung. Der Nutzer trägt die alleinige Verantwortung für alle Handlungen, die auf der Grundlage dieser Informationen getroffen werden. Der Autor haftet nicht für etwaige Verluste oder Schäden, die aus der Nutzung entstehen.
