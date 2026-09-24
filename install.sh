#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/baibiaowang/VPS-SQLite-API.git"
APP_DIR="/opt/eastmoney"
ENV_DIR="/etc/eastmoney"
ENV_FILE="$ENV_DIR/eastmoney.env"
SERVICE_USER="eastmoney"

if [ "$(id -u)" -ne 0 ]; then echo "请使用 root 或 sudo 运行。"; exit 1; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip sqlite3 git curl openssl ca-certificates

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard origin/main
else
  mkdir -p "$APP_DIR"
  git clone --depth 1 "$REPO" "$APP_DIR"
fi

mkdir -p "$ENV_DIR" "$APP_DIR/data/raw" "$APP_DIR/data/backup" "$APP_DIR/logs"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    ADMIN_PASS="$ADMIN_PASSWORD"
  else
    echo "首次安装需要设置管理面板密码。"
    read -r -s -p "管理密码: " ADMIN_PASS < /dev/tty || true
    echo
    read -r -s -p "再次输入: " ADMIN_PASS2 < /dev/tty || true
    echo
    if [ "$ADMIN_PASS" != "$ADMIN_PASS2" ] || [ "${#ADMIN_PASS}" -lt 10 ]; then
      echo "密码为空、长度不足10位或两次不一致。"
      exit 1
    fi
  fi

  SALT="$(openssl rand -hex 16)"
  PASSWORD_HASH="$("$APP_DIR/venv/bin/python" - "$ADMIN_PASS" "$SALT" <<'PY'
import hashlib, sys
password=sys.argv[1].encode()
salt=bytes.fromhex(sys.argv[2])
rounds=310000
digest=hashlib.pbkdf2_hmac("sha256", password, salt, rounds, dklen=32).hex()
print(f"pbkdf2_sha256${salt.hex()}${rounds}${digest}")
PY
)"
  API_TOKEN="${EASTMONEY_API_TOKEN:-$(openssl rand -hex 32)}"
  API_HASH="$(printf '%s' "$API_TOKEN" | sha256sum | awk '{print $1}')"
  SESSION_SECRET="${EASTMONEY_SESSION_SECRET:-$(openssl rand -hex 32)}"

  umask 077
  cat > "$ENV_FILE" <<EOF
EASTMONEY_BASE_DIR=$APP_DIR
EASTMONEY_DB=$APP_DIR/data/eastmoney.db
EASTMONEY_RAW_DIR=$APP_DIR/data/raw
EASTMONEY_BACKUP_DIR=$APP_DIR/data/backup
EASTMONEY_LOG_DIR=$APP_DIR/logs
EASTMONEY_API_TOKEN_HASH=$API_HASH
EASTMONEY_ADMIN_PASSWORD_HASH=$PASSWORD_HASH
EASTMONEY_SESSION_SECRET=$SESSION_SECRET
EASTMONEY_PORT=8080
EASTMONEY_PAGE_SIZE=100
EASTMONEY_FETCH_DAYS_BACK=1
EASTMONEY_BACKUP_DAILY_KEEP=7
EOF
  chmod 600 "$ENV_FILE"

  echo
  echo "=============================================="
  echo "首次安装生成的 API Token（只显示这一次）："
  echo "$API_TOKEN"
  echo "=============================================="
fi

cp "$APP_DIR/deploy/eastmoney-api.service" /etc/systemd/system/eastmoney-api.service
cp "$APP_DIR/deploy/eastmoney-fetch.service" /etc/systemd/system/eastmoney-fetch.service
cp "$APP_DIR/deploy/eastmoney-fetch.timer" /etc/systemd/system/eastmoney-fetch.timer
cp "$APP_DIR/deploy/eastmoney-backup.service" /etc/systemd/system/eastmoney-backup.service
cp "$APP_DIR/deploy/eastmoney-backup.timer" /etc/systemd/system/eastmoney-backup.timer
cp "$APP_DIR/deploy/eastmoney-scheduler.service" /etc/systemd/system/eastmoney-scheduler.service
cp "$APP_DIR/deploy/eastmoney-scheduler.timer" /etc/systemd/system/eastmoney-scheduler.timer

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chmod 750 "$APP_DIR"
chmod 700 "$APP_DIR/data" "$APP_DIR/data/raw" "$APP_DIR/data/backup" "$APP_DIR/logs"

runuser -u "$SERVICE_USER" -- "$APP_DIR/venv/bin/python" -m app.db

systemctl daemon-reload
systemctl enable --now eastmoney-api.service
# 旧版固定 23:30 定时器会绕过面板计划；由 scheduler.timer 统一负责调度。
systemctl disable --now eastmoney-fetch.timer 2>/dev/null || true
systemctl enable --now eastmoney-backup.timer
systemctl enable --now eastmoney-scheduler.timer

echo
echo "安装完成。"
echo "管理面板: http://SERVER_IP:8080/admin/login"
echo "API 文档: http://SERVER_IP:8080/docs"
echo "服务状态: systemctl status eastmoney-api"
echo "立即抓取: systemctl start eastmoney-fetch.service"
echo "调度器: systemctl status eastmoney-scheduler.timer"
