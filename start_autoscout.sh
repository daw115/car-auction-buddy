#!/bin/bash
cd /Users/dawidslabicki/Documents/Claude/carsmillionaire/usa-car-finder
exec venv/bin/python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
