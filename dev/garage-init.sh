#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose}"
garage() { $COMPOSE exec -T garage /garage "$@"; }

node_id="$(garage node id -q | cut -d@ -f1)"
garage layout assign -z dev -c 1G "$node_id"
garage layout apply --version 1
garage key import --yes GK000000000000000000000000 0000000000000000000000000000000000000000000000000000000000000000
garage bucket create uploads
garage bucket allow --read --write --owner uploads --key GK000000000000000000000000
