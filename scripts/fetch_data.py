"""Download public data once; record source/hash, never alter historical evidence."""

from pathlib import Path
import hashlib
import json
import urllib.request
import time

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/cache"
DEST.mkdir(parents=True, exist_ok=True)
SOURCES = {'longmemeval_s_cleaned.json': 'https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json'}
manifest = ROOT / "data/download_manifest.json"
expected = (
    {r["file"]: r for r in json.loads(manifest.read_text())}
    if manifest.exists()
    else {}
)
records = []
for name, url in SOURCES.items():
    p = DEST / name
    if not p.exists():
        part = p.with_suffix(p.suffix + ".part")
        with urllib.request.urlopen(url, timeout=180) as response, part.open("wb") as f:
            while data := response.read(1024 * 1024):
                f.write(data)
        part.rename(p)
    records.append(
        {
            "file": name,
            "source": url,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
    )
    if name in expected and (
        records[-1]["sha256"] != expected[name]["sha256"]
        or records[-1]["bytes"] != expected[name]["bytes"]
    ):
        raise ValueError(
            "Downloaded data differs from retained manifest; preserve it and use an explicitly versioned data directory"
        )
    print(json.dumps(records[-1]), flush=True)
if not manifest.exists():
    manifest.write_text(json.dumps(records, indent=2))
