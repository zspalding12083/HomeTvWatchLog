#!/usr/bin/env bash
# Keep this folder (the source of truth and local backup) and the Orange Pi in step.
#
#   deploy/sync.sh push     test locally, copy code to the Pi, restart, check it's up
#   deploy/sync.sh backup   copy the Pi's database and service file into backups/
#   deploy/sync.sh check    show anything that differs between here and the Pi
#
# Needs: SSH keys for spalding@10.0.0.10, /opt/watchlog/watchlog owned by spalding,
# and /etc/sudoers.d/watchlog-restart (NOPASSWD for "systemctl restart watchlog").
# First-time setup on the Pi: see README.md.
set -euo pipefail

PI=${PI:-spalding@10.0.0.10}
HERE=$(cd "$(dirname "$0")/.." && pwd)
CODE=/opt/watchlog/watchlog
DB=/var/lib/watchlog/watchlog.db
KEEP=30                                   # database snapshots to keep
RSYNC=(rsync -a --exclude __pycache__ --exclude '*.pyc')
cd "$HERE"

push() {
    python3 -m unittest discover -s tests -t . -q
    "${RSYNC[@]}" --delete watchlog/ "$PI:$CODE/"
    ssh "$PI" 'sudo -n /usr/bin/systemctl restart watchlog && sleep 2 && systemctl is-active watchlog'
    curl -fsS --max-time 10 "http://${PI#*@}:9280/api/summary" >/dev/null && echo "dashboard is up"
}

backup() {
    mkdir -p backups
    local stamp; stamp=$(date +%Y%m%d-%H%M)
    # sqlite's online backup: a consistent copy even while the service is writing
    ssh "$PI" "python3 -c 'import sqlite3; s=sqlite3.connect(\"file:$DB?mode=ro\", uri=True); d=sqlite3.connect(\"/tmp/watchlog-backup.db\"); s.backup(d); d.close()'"
    rsync -a "$PI:/tmp/watchlog-backup.db" "backups/watchlog-$stamp.db"
    ssh "$PI" 'rm -f /tmp/watchlog-backup.db'
    # the Pi's unit goes into backups/, never over deploy/watchlog.service (the repo's
    # version may be newer and not installed yet; "check" shows any difference)
    rsync -a "$PI:/etc/systemd/system/watchlog.service" "backups/watchlog-$stamp.service"
    ls -1t backups/watchlog-*.db | tail -n +$((KEEP + 1)) | xargs -r rm --
    ls -1t backups/watchlog-*.service | tail -n +$((KEEP + 1)) | xargs -r rm --
    echo "backed up to backups/watchlog-$stamp.db ($(du -h "backups/watchlog-$stamp.db" | cut -f1))"
}

check() {
    echo "code on the Pi that differs from here:"
    "${RSYNC[@]}" -nci "$PI:$CODE/" watchlog/ | grep -v '^\.' || echo "  none"
    echo "service file:"
    ssh "$PI" cat /etc/systemd/system/watchlog.service | diff -q - deploy/watchlog.service >/dev/null \
        && echo "  same" || echo "  DIFFERENT (install deploy/watchlog.service on the Pi; see STATUS.md)"
}

case "${1:-}" in
    push) push ;;
    backup) backup ;;
    check) check ;;
    *) sed -n '2,10p' "$0"; exit 1 ;;
esac
