#!/bin/bash
# 启动 Quant Lite 服务（生产模式：公网可访问，多 worker）
set -e
cd "$(dirname "$0")/.."

HOST="${QUANT_HOST:-0.0.0.0}"
PORT="${QUANT_PORT:-8001}"
WORKERS="${QUANT_WORKERS:-2}"

PIDFILE=/tmp/quant-lite.pid
LOGFILE=server.log

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Stopping existing server (PID $(cat "$PIDFILE"))..."
    kill "$(cat "$PIDFILE")"
    sleep 2
fi
pkill -f "uvicorn app.main" 2>/dev/null || true
sleep 1

nohup .venv/bin/uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --access-log \
    > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
disown

sleep 3
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Server started (master PID $(cat "$PIDFILE")), $WORKERS workers, $HOST:$PORT"
    echo "Health: $(curl -s "http://localhost:$PORT/api/health")"
else
    echo "Server failed to start. Last 20 log lines:"
    tail -20 "$LOGFILE"
    exit 1
fi
