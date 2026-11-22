#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"

dashboard=http://127.0.0.1:5173/dashboard
api_health=http://127.0.0.1:8000/api/health
pg_ctl=.venv/lib/python3.11/site-packages/pgserver/pginstall/bin/pg_ctl

get() { curl --noproxy '*' -fsS --max-time 2 "$1" 2>/dev/null; }
api_ready() { get "$1" | grep -q '"llm_provider"'; }
web_ready() { get "$dashboard" | grep -q '<title>PayPilot AI'; }
ready() { web_ready && api_ready http://127.0.0.1:5173/api/health; }

if ready; then
    echo "PayPilot 已运行：$dashboard"
    exit 0
fi

# A fresh checkout uses Compose. This workspace can also reuse its initialized native stack.
if [[ ! -f .local/pgdata/PG_VERSION || ! -x $pg_ctl || ! -x .venv/bin/alembic ||
      ! -f frontend/node_modules/vite/bin/vite.js ]] || ! command -v node >/dev/null; then
    if ! docker compose version >/dev/null 2>&1; then
        echo "首次启动需要 Docker Compose。请安装并启动 Docker 后重新运行 ./start.sh。" >&2
        exit 1
    fi
    compose=(docker compose -f infra/compose.yaml --profile demo)
    if [[ -f .env ]]; then compose+=(--env-file .env); fi
    "${compose[@]}" up --build -d --wait
    for ((i=0; i<30; i++)); do
        if ready; then
            echo "PayPilot 已启动：$dashboard"
            echo "停止：docker compose -f infra/compose.yaml --profile demo stop"
            exit 0
        fi
        sleep 1
    done
    echo "前端或 API 未就绪，请运行 docker compose -f infra/compose.yaml --profile demo logs。" >&2
    exit 1
fi

api_pid=
web_pid=
cleanup() {
    if [[ -n $web_pid ]]; then kill "$web_pid" 2>/dev/null || true; fi
    if [[ -n $api_pid ]]; then kill "$api_pid" 2>/dev/null || true; fi
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! "$pg_ctl" -D .local/pgdata status >/dev/null; then
    "$pg_ctl" -D .local/pgdata -l .local/postgres.log -o '-h 127.0.0.1 -p 55432 -k /tmp' -w start
fi
if ! api_ready "$api_health"; then
    (
        if [[ -f .env ]]; then set -a; . ./.env; set +a; fi
        .venv/bin/alembic -c backend/alembic.ini upgrade head
        .venv/bin/python scripts/seed_payments.py
    )
    ./scripts/start_api.sh &
    api_pid=$!
fi
if ! web_ready; then
    (cd frontend && exec node node_modules/vite/bin/vite.js) &
    web_pid=$!
fi

children_alive() {
    [[ -z $api_pid ]] || kill -0 "$api_pid" 2>/dev/null || return 1
    [[ -z $web_pid ]] || kill -0 "$web_pid" 2>/dev/null || return 1
}
for ((i=0; i<30; i++)); do
    children_alive || break
    if ready; then
        echo "PayPilot 已启动：$dashboard"
        echo "按 Ctrl+C 停止本次启动的前后端。"
        while children_alive; do sleep 1; done
        echo "PayPilot 服务已退出，请检查上方日志。" >&2
        exit 1
    fi
    sleep 1
done
echo "PayPilot 未就绪，请检查上方日志及端口 8000、5173。" >&2
exit 1
