#!/usr/bin/env bash
# One-time setup of watchlog on the Pi. Asks for the Pi's sudo password once.
# Afterwards use deploy/sync.sh push to deploy changes.
set -euo pipefail

PI=${PI:-spalding@10.0.0.10}
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"

python3 -m unittest discover -s tests -t . -q
rsync -a --exclude __pycache__ --exclude '*.pyc' watchlog deploy/watchlog.service "$PI:/tmp/watchlog-install/"
ssh -t "$PI" 'set -e
    id watchlog >/dev/null 2>&1 || sudo useradd --system --no-create-home --shell /usr/sbin/nologin watchlog
    # the data folder is private to the watchlog group; this login joins it so
    # deploy/sync.sh backup can still read the database
    sudo usermod -aG watchlog "$(id -un)"
    sudo mkdir -p /opt/watchlog
    sudo chown spalding: /opt/watchlog
    rm -rf /opt/watchlog/watchlog && mv /tmp/watchlog-install/watchlog /opt/watchlog/
    echo "spalding ALL=(root) NOPASSWD: /usr/bin/systemctl restart watchlog" | sudo tee /etc/sudoers.d/watchlog-restart >/dev/null
    sudo chmod 440 /etc/sudoers.d/watchlog-restart
    sudo visudo -cf /etc/sudoers.d/watchlog-restart
    sudo install -m 644 /tmp/watchlog-install/watchlog.service /etc/systemd/system/watchlog.service
    rm -rf /tmp/watchlog-install
    sudo systemctl daemon-reload
    sudo systemctl enable --now watchlog
    sleep 2 && systemctl is-active watchlog'
curl -fsS --max-time 10 "http://${PI#*@}:9280/api/summary" >/dev/null && echo "dashboard is up: http://${PI#*@}:9280"
