#!/bin/bash
# Inicia CabidaApp usando el virtualenv del proyecto
cd "$(dirname "$0")"
pkill -f "streamlit run app.py" 2>/dev/null
venv/bin/streamlit run app.py --server.port 8501
