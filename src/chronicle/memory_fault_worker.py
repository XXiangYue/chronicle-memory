"""Actual ingest-process exit after the FTS insert but before SQLite commit."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from . import memory

original = memory.db


@contextmanager
def crash_db(path):
    with original(path) as c:

        class Wrapped:
            def execute(self, sql, *args):
                r = c.execute(sql, *args)
                if sql.startswith("INSERT INTO chunks"):
                    os._exit(74)
                return r

            def __getattr__(self, name):
                return getattr(c, name)

        yield Wrapped()


m = memory.Memory(Path(sys.argv[1]), "ingest-witness")
memory.db = crash_db
m.ingest(json.loads(Path(sys.argv[2]).read_text()))
