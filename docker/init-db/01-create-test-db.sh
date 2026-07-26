#!/bin/sh
# Runs once, when the Postgres data volume is first initialised.
# Creates the database the test suite uses, so a fresh clone needs no manual step.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE taskapi_test;
EOSQL
