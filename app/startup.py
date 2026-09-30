"""Wait for the persistent database, migrate once, then replace this process."""
import logging
import os
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .db import engine


def wait_for_database(db_engine=engine, attempts=12, pause=time.sleep):
    for attempt in range(attempts):
        try:
            with db_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == attempts - 1:
                raise RuntimeError("Database unavailable; startup stopped") from None
            # Never print a connection exception: it can contain credentials.
            logging.warning("Database not ready; retry %s/%s", attempt + 1, attempts)
            pause(5)


def main():
    wait_for_database()
    # Migration failures must stop startup, not be hidden by a retry loop.
    command.upgrade(Config("alembic.ini"), "head")
    engine.dispose()
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0",
                          "--port", os.environ.get("PORT", "8000")])


if __name__ == "__main__":
    main()
