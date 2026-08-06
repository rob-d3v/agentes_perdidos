#!/usr/bin/env bash
# Guardian installer — run AS ROOT on the target VPS.
# Installs backup_guardian.py + restore_guardian.py, ensures boto3, writes
# /etc/guardian/config.json from env vars, and schedules the daily cron.
#
# Required env:
#   GUARDIAN_HOST_LABEL   unique label for this VPS in B2 (e.g. coolify / oracle)
#   B2_ENDPOINT  B2_REGION  B2_KEY_ID  B2_APPLICATION_KEY  B2_BUCKET
# Optional env:
#   GUARDIAN_BACKUP_DIR (default /root/backups)
#   GUARDIAN_CRON_HOUR  (default 3)         WEEKLY_WEEKDAY (default 5 = Saturday)
#   LOCAL_KEEP (1)  B2_DAILY_KEEP (3)  B2_WEEKLY_KEEP (3)
#   EXCLUDE_JSON  (default ["^[0-9a-f]{64}$","redis"])
#   WA_API_URL WA_INSTANCE WA_API_KEY WA_NUMBER   (WhatsApp; optional)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${GUARDIAN_HOST_LABEL:?set GUARDIAN_HOST_LABEL}"
: "${B2_KEY_ID:?}" ; : "${B2_APPLICATION_KEY:?}" ; : "${B2_BUCKET:?}"
: "${B2_REGION:=us-east-005}"
: "${B2_ENDPOINT:=https://s3.${B2_REGION}.backblazeb2.com}"
: "${GUARDIAN_BACKUP_DIR:=/root/backups}"
: "${GUARDIAN_CRON_HOUR:=3}"
: "${WEEKLY_WEEKDAY:=5}"
: "${LOCAL_KEEP:=1}"
: "${B2_DAILY_KEEP:=3}"
: "${B2_WEEKLY_KEEP:=3}"
# NB: default kept out of ${:=} because the '}' in {64} would close the expansion early.
if [ -z "${EXCLUDE_JSON:-}" ]; then EXCLUDE_JSON='["^[0-9a-f]{64}$","redis"]'; fi

echo "[guardian] installing boto3 ..."
if ! python3 -c "import boto3" 2>/dev/null; then
  pip3 install --quiet --break-system-packages boto3 2>/dev/null \
    || pip3 install --quiet boto3 2>/dev/null \
    || (apt-get update -qq && apt-get install -y -qq python3-boto3)
fi
python3 -c "import boto3; print('[guardian] boto3', boto3.__version__)"

echo "[guardian] copying scripts ..."
install -m 755 "$SRC_DIR/backup_guardian.py"  /usr/local/bin/guardian-backup
install -m 755 "$SRC_DIR/restore_guardian.py" /usr/local/bin/guardian-restore

echo "[guardian] writing /etc/guardian/config.json ..."
mkdir -p /etc/guardian
WA_BLOCK="null"
if [ -n "${WA_API_URL:-}" ]; then
  WA_BLOCK="{\"api_url\":\"$WA_API_URL\",\"instance\":\"$WA_INSTANCE\",\"api_key\":\"$WA_API_KEY\",\"target_number\":\"$WA_NUMBER\"}"
fi
cat > /etc/guardian/config.json <<JSON
{
  "host_label": "$GUARDIAN_HOST_LABEL",
  "backup_dir": "$GUARDIAN_BACKUP_DIR",
  "local_keep": $LOCAL_KEEP,
  "weekly_weekday": $WEEKLY_WEEKDAY,
  "b2_daily_keep": $B2_DAILY_KEEP,
  "b2_weekly_keep": $B2_WEEKLY_KEEP,
  "exclude_patterns": $EXCLUDE_JSON,
  "b2": {
    "endpoint": "$B2_ENDPOINT",
    "region": "$B2_REGION",
    "key_id": "$B2_KEY_ID",
    "application_key": "$B2_APPLICATION_KEY",
    "bucket": "$B2_BUCKET"
  },
  "whatsapp": $WA_BLOCK
}
JSON
chmod 600 /etc/guardian/config.json

if command -v crontab >/dev/null 2>&1; then
  echo "[guardian] scheduling via cron (daily ${GUARDIAN_CRON_HOUR}:00) ..."
  CRON_LINE="0 ${GUARDIAN_CRON_HOUR} * * * /usr/bin/python3 /usr/local/bin/guardian-backup run >> /var/log/guardian-backup.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v 'guardian-backup' ; echo "$CRON_LINE" ) | crontab -
else
  echo "[guardian] no crontab — scheduling via systemd timer (daily ${GUARDIAN_CRON_HOUR}:00) ..."
  cat > /etc/systemd/system/guardian-backup.service <<UNIT
[Unit]
Description=Guardian VPS backup
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/bin/guardian-backup run
StandardOutput=append:/var/log/guardian-backup.log
StandardError=append:/var/log/guardian-backup.log
UNIT
  cat > /etc/systemd/system/guardian-backup.timer <<UNIT
[Unit]
Description=Daily Guardian VPS backup

[Timer]
OnCalendar=*-*-* ${GUARDIAN_CRON_HOUR}:00:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now guardian-backup.timer
  systemctl list-timers guardian-backup.timer --no-pager 2>/dev/null | head -3
fi

echo "[guardian] done. Verify:"
echo "  guardian-backup check && guardian-backup list"
