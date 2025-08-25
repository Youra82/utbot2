#!/bin/bash
# Stellt sicher, dass das Skript im richtigen Verzeichnis ausgeführt wird
cd /home/ubuntu/utbot2/code/strategies/envelope/
# Aktiviert die Python-Umgebung und startet den Bot
source /home/ubuntu/utbot2/code/.venv/bin/activate
python3 run.py
