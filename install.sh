#!/bin/bash

echo ">>> Updating the server..."
sudo apt-get update
sudo apt-get upgrade -y

echo ">>> Installing pip and other essentials..."
sudo apt-get install python3-pip -y
sudo apt-get install jq -y

echo ">>> Installing virtual environment and packages..."
cd "$(dirname "$0")/code" # Wechsle in das 'code'-Verzeichnis relativ zum Skript
sudo apt-get install python3-venv -y
python3 -m venv .venv
source .venv/bin/activate
echo ">>> Installing requirements..."
pip install -r ../requirements.txt
echo ">>> Installation complete!"
