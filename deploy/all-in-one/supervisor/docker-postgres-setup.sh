#!/usr/bin/env bash
set -Eeo pipefail

# print large warning if POSTGRES_PASSWORD is long
# error if both POSTGRES_PASSWORD is empty and POSTGRES_HOST_AUTH_METHOD is not 'trust'
# print large warning if POSTGRES_HOST_AUTH_METHOD is set to 'trust'
# assumes database is not set up, ie: [ -z "$DATABASE_ALREADY_EXISTS" ]
docker_verify_minimum_env() {
  if [[ -z "$POSTGRES_USER" ]]; then
    echo "Must set POSTGRES_USER" 2>&1
    exit 1;
  fi
  if [[ -z "$POSTGRES_DB" ]]; then
    echo "Must set POSTGRES_DB" 2>&1
    exit 1;
  fi
  if [[ -z "$POSTGRES_PASSWORD" ]]; then
    echo "Must set POSTGRES_PASSWORD" 2>&1
    exit 1;
  fi
  if [[ -z "$PGDATA" ]]; then
    echo "Must set PGDATA" 2>&1
    exit 1;
  fi
	# check password first so we can output the warning before postgres
	# messes it up
	if [ "${#POSTGRES_PASSWORD}" -ge 100 ]; then
		cat >&2 <<-'EOWARN'
			WARNING: The supplied POSTGRES_PASSWORD is 100+ characters.
			  This will not work if used via PGPASSWORD with "psql".
			  https://www.postgresql.org/message-id/flat/E1Rqxp2-0004Qt-PL%40wrigleys.postgresql.org (BUG #6412)
			  https://github.com/docker-library/postgres/issues/507
		EOWARN
	fi
}

# Execute sql script
docker_process_sql() {
	local query_runner=( psql -v ON_ERROR_STOP=1 --no-password --no-psqlrc --dbname "$POSTGRES_DB" )
	"${query_runner[@]}" "$@"
}

# create initial database
# uses environment variables for input: POSTGRES_DB
docker_setup_db() {
	local dbAlreadyExists
	dbAlreadyExists="$(
		docker_process_sql --dbname postgres --set db="$POSTGRES_DB" --tuples-only <<-'EOSQL'
			SELECT 1 FROM pg_database WHERE datname = :'db' ;
		EOSQL
	)"
	if [ -z "$dbAlreadyExists" ]; then
		docker_process_sql --dbname postgres \
		  --set db="$POSTGRES_DB" \
		  --set pass="$POSTGRES_PASSWORD" \
		  --set user="$POSTGRES_USER" \
		  <<-'EOSQL'
			CREATE DATABASE :"db";
			create user :"user" with encrypted password :'pass';
			grant all privileges on database :"db" to :"user";
		EOSQL
	fi
}

# start postgresql server for setting up or running scripts
docker_temp_server_start() {
	# internal start of server in order to allow setup using psql client
	PGUSER="${PGUSER:-$POSTGRES_USER}" \
	pg_ctlcluster 11 main start -- -w -o "-c listen_addresses=''"
}

# stop postgresql server after done setting up user and running scripts
docker_temp_server_stop() {
	PGUSER="${PGUSER:-postgres}" \
	pg_ctlcluster 11 main stop -- -m fast -w
}

_main() {
    if [ "$(id -u)" = '0' ]; then
      # then restart script as postgres user
      su postgres -c "${BASH_SOURCE[0]}" "$@"
    else
      ALREADY_SETUP_INDICATOR_FILE="$PGDATA/baserow_db_setup"
      if [ -f "$ALREADY_SETUP_INDICATOR_FILE" ]; then
        echo
        echo 'PostgreSQL Database directory appears to contain a database; Skipping initialization'
        echo
      else
        docker_verify_minimum_env

        cp -pR /var/lib/postgresql/11/main/. "$DATA_DIR/postgres/"
        docker_temp_server_start "$@"
        docker_setup_db
        touch "$ALREADY_SETUP_INDICATOR_FILE"
        docker_temp_server_stop

        echo
        echo 'PostgreSQL init process complete; ready for start up.'
        echo
      fi
    fi
}

_main "$@"
