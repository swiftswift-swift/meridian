#!/bin/sh
# Container entrypoint: wait for the database, create the schema, seed once, then exec the
# command. `exec` matters -- without it uvicorn runs as a child of this shell and never
# receives SIGTERM, so the container is killed rather than shut down.
set -eu

wait_for_database() {
    # Compose healthchecks cover the common case, but a database can also be an external
    # service that starts slowly, so the application waits rather than crash-looping.
    attempt=1
    until python -c "
import asyncio, sys
from app.settings import Settings
from app.infra.db import Database

async def main() -> None:
    database = Database.from_settings(Settings())
    try:
        healthy = await database.healthy()
    finally:
        await database.dispose()
    sys.exit(0 if healthy else 1)

asyncio.run(main())
" 2>/dev/null; do
        if [ "$attempt" -ge 30 ]; then
            echo "database did not become reachable after 30 attempts" >&2
            exit 1
        fi
        echo "waiting for the database (attempt ${attempt})"
        attempt=$((attempt + 1))
        sleep 2
    done
}

if [ "${SKIP_DB_BOOTSTRAP:-0}" != "1" ]; then
    wait_for_database

    # The seed is idempotent, so running it on every start is safe and keeps a fresh volume
    # usable without a separate manual step.
    echo "seeding demo data"
    python -m scripts.seed_demo
fi

exec "$@"
