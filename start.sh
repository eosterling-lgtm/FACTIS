#!/bin/bash
# Inicia CabidaApp usando el virtualenv del proyecto
cd "$(dirname "$0")"
pkill -f "streamlit run solum.py" 2>/dev/null
venv/bin/streamlit run solum.py --server.port 8501
