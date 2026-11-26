#!/usr/bin/env bash
# One-command install of the Helpdesk Agent demo on an Ubuntu server (e.g. an Oracle free VM).
#   curl -fsSL https://raw.githubusercontent.com/MontaserAlajamy/helpdesk-agent/main/deploy/vps/install.sh | sudo bash
# Re-run it to update. It asks once for an OpenRouter key (leave empty for the offline fake model).
set -euo pipefail
APP=/opt/helpdesk-agent
DATA=/var/lib/helpdesk
ENVF=/etc/helpdesk-agent.env
PORT=8080
MODEL=nvidia/nemotron-3.5-super-vl:free

echo "== packages"
apt-get update -qq && apt-get install -y -qq git curl ca-certificates iptables >/dev/null
id -u helpdesk >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin helpdesk
mkdir -p "$DATA" && chown helpdesk "$DATA"

echo "== code"
if [ -d "$APP/.git" ]; then git -c safe.directory="$APP" -C "$APP" pull -q --ff-only; else git clone -q https://github.com/MontaserAlajamy/helpdesk-agent "$APP"; fi
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
cd "$APP" && UV_PYTHON_INSTALL_DIR=/opt/uv-python uv sync --frozen --no-dev -q
chown -R helpdesk "$APP"

echo "== settings ($ENVF)"
if [ ! -f "$ENVF" ]; then
  KEY=""
  if [ -r /dev/tty ]; then
    printf "OpenRouter API key for the demo (input hidden, Enter = offline fake model): " > /dev/tty
    read -rs KEY < /dev/tty || true; echo > /dev/tty
  fi
  umask 077
  if [ -n "$KEY" ]; then
    printf 'DEMO_MODE=1\nDATABASE_URL=sqlite+aiosqlite:///%s/demo.db\nLLM_PROVIDER=openai\nOPENAI_BASE_URL=https://openrouter.ai/api/v1\nLLM_MODEL=%s\nOPENAI_API_KEY=%s\n' "$DATA" "$MODEL" "$KEY" > "$ENVF"
  else
    printf 'DEMO_MODE=1\nDATABASE_URL=sqlite+aiosqlite:///%s/demo.db\nLLM_PROVIDER=fake\n' "$DATA" > "$ENVF"
  fi
  chmod 600 "$ENVF"
fi

echo "== service"
cat > /etc/systemd/system/helpdesk-agent.service <<UNIT
[Unit]
Description=Helpdesk Agent demo
After=network-online.target
[Service]
User=helpdesk
WorkingDirectory=$APP
EnvironmentFile=$ENVF
ExecStart=$APP/.venv/bin/uvicorn --factory helpdesk.api:app_factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=3
MemoryMax=400M
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q helpdesk-agent
systemctl restart helpdesk-agent

echo "== firewall (port $PORT)"
iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport $PORT -j ACCEPT
command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true

echo "== waiting for the app to start (up to 90 s)"
for i in $(seq 1 45); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 2; done
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "OK: running on port $PORT. Model: $(curl -fsS http://127.0.0.1:$PORT/v1/meta | sed 's/.*"model":"\([^"]*\)".*/\1/')"
  echo "Change the model or key: sudo nano $ENVF && sudo systemctl restart helpdesk-agent"
else
  echo "Not answering. Last log lines:"; journalctl -u helpdesk-agent -n 25 --no-pager || true
fi
