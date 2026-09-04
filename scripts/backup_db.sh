#!/bin/sh
set -eu

umask 077

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [backup-file]" >&2
  exit 2
fi

backup_file=${1:-"backups/llps-explorer-$(date -u +%Y%m%dT%H%M%SZ).dump"}
backup_dir=$(dirname -- "$backup_file")
if [ -e "$backup_file" ]; then
  echo "Backup destination already exists; refusing to overwrite it." >&2
  exit 1
fi
mkdir -p -- "$backup_dir"

temporary_file="${backup_file}.partial.$$"
trap 'rm -f -- "$temporary_file"' EXIT HUP INT TERM

docker compose exec -T postgres sh -eu -c \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
  >"$temporary_file"

if [ ! -s "$temporary_file" ]; then
  echo "Backup is empty; refusing to publish it." >&2
  exit 1
fi

mv -- "$temporary_file" "$backup_file"
trap - EXIT HUP INT TERM
echo "Backup written to $backup_file"
