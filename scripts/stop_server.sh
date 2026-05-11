#!/bin/bash
PIDFILE=/tmp/quant-lite.pid
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    rm -f "$PIDFILE"
    echo "Stopped"
else
    pkill -f "uvicorn app.main" && echo "Killed by name"
    rm -f "$PIDFILE"
fi
