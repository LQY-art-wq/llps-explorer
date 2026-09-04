#!/bin/sh
set -eu

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-replace" ]; then
  echo "Usage: $0 backup-file --confirm-replace" >&2
  echo "This replaces the current PostgreSQL schema and stops application workers briefly." >&2
  exit 2
fi

backup_file=$1
if [ ! -f "$backup_file" ] || [ ! -s "$backup_file" ]; then
  echo "Backup file is missing or empty." >&2
  exit 1
fi

# Validate the archive before interrupting application services.
docker compose exec -T postgres pg_restore --list <"$backup_file" >/dev/null

restart_services=false
cleanup() {
  if [ "$restart_services" = true ]; then
    docker compose start backend worker >/dev/null
  fi
}
trap cleanup EXIT HUP INT TERM

restart_services=true
docker compose stop backend worker

docker compose exec -T postgres sh -eu -c \
  'exec pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction' \
  <"$backup_file"

docker compose run --rm migrate
docker compose start backend worker
restart_services=false
trap - EXIT HUP INT TERM
echo "Restore completed and application services restarted."
