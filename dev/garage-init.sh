#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose}"
garage() { $COMPOSE exec -T garage /garage "$@"; }

tries=30
until garage status >/dev/null 2>&1; do
    tries=$((tries - 1))
    if [ "$tries" -eq 0 ]; then
        echo "Garage did not start" >&2
        exit 1
    fi
    sleep 1
done

node_id="$(garage node id -q | cut -d@ -f1)"
garage layout assign -z dev -c 1G "$node_id"
garage layout apply --version 1
garage key import --yes GK000000000000000000000000 0000000000000000000000000000000000000000000000000000000000000000
garage bucket create uploads
garage bucket allow --read --write --owner uploads --key GK000000000000000000000000
