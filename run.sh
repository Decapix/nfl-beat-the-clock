#!/usr/bin/env bash
# one command: deps -> data -> build -> dashboard
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f data/plays.csv ]; then
  if [ -n "$RVR_DATA" ] && [ -f "$RVR_DATA/plays.csv" ]; then
    ln -s "$RVR_DATA" data
  else
    echo "data/ not found, pulling the Big Data Bowl regional data (about 1 GB) ..."
    git clone --depth 1 https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data .bdb_tmp
    mv .bdb_tmp/data data && rm -rf .bdb_tmp
  fi
fi

if [ ! -f outputs/race_by_play.parquet ]; then
  python build.py
fi

streamlit run app.py
