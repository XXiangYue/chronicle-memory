"""Interrupted indexing with real process exit/SQLite recovery, no model fixture."""

import json
from pathlib import Path
import subprocess
import sys
from .common import ROOT, freeze, write_json, db, digest
from .memory import Memory


def run(out):
    freeze(
        out,
        {
            "fault": "Process os._exit(74) after real FTS INSERT inside Memory.ingest transaction, before commit",
            "source": {
                n: digest((ROOT / "src/chronicle" / n).read_bytes())
                for n in ("memory.py", "memory_fault_worker.py", "memory_faults.py")
            },
        },
    )
    if (out / "summary.json").exists():
        return
    sources = [
        {
            "id": "new-source",
            "observed_at": "2026-10-01",
            "text": "索引中断见证：预算为329元。",
        }
    ]
    write_json(out / "sources.json", sources)
    path = out / "memory.sqlite"
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "chronicle.memory_fault_worker",
            str(path),
            str(out / "sources.json"),
        ],
        capture_output=True,
        timeout=30,
    )
    with db(path) as c:
        before = {
            "sources": c.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "chunks": c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "integrity": c.execute("PRAGMA integrity_check").fetchone()[0],
        }
    m = Memory(path, "ingest-witness")
    m.ingest(sources)
    m.ingest(sources)
    with db(path) as c:
        after = {
            "sources": c.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "chunks": c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
    result = {
        "exit_code": child.returncode,
        "before_retry": before,
        "after_retry_twice": after,
        "passed": child.returncode == 74
        and before == {"sources": 0, "chunks": 0, "integrity": "ok"}
        and after == {"sources": 1, "chunks": 1},
        "scope": "Single controlled ingest/FTS transaction exit, not all hardware/filesystem crash modes",
    }
    write_json(out / "summary.json", result)
    print(result)


if __name__ == "__main__":
    run(ROOT / "evidence/P2/ingest_exit_v1")
