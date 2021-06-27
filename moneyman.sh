#!/bin/bash
set -e
source venv/bin/activate
pip3 install -r requirements.txt
python3 moneyman.py

