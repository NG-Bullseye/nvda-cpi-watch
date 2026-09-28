#!/usr/bin/env bash
# bootstrap.sh — idempotentes Aufsetzen: venv + requirements + .env aus Vorlage. Startet weder Server noch Agent.
set -euo pipefail
cd "$(dirname "$0")"
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo ".env aus Vorlage angelegt — FINNHUB_API_KEY eintragen"; }
mkdir -p cache
echo "ok — Agent starten: siehe README § Quickstart"
