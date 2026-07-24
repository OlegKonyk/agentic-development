#!/bin/sh
# Runs via docker-entrypoint-initdb.d on every db boot (PGDATA is tmpfs):
# creates the extra database the fast unit/integration tests use.
set -eu
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE DATABASE taskboard_test OWNER $POSTGRES_USER"
