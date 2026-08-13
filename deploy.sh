#!/usr/bin/env bash
set -euo pipefail

cd /srv/workflow/app
git pull --ff-only origin main
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
curl --fail --silent --show-error http://127.0.0.1/healthz
echo
