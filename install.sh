#!/bin/bash
echo "--- Richte gemini-trader ein ---"
sudo apt-get update -y && sudo apt-get install python3-pip python3-venv -y
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
echo "✔ Einrichtung abgeschlossen. Umgebung '.venv' ist bereit."
