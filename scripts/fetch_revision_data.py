"""Fetch the fixed Supersede episodes and reference scorer by immutable revision."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

DATA = "https://huggingface.co/datasets/vedant33/supersede-rl-episodes/resolve/e44c0852a727d17a9c3f38022691fd7fa285ff8c/data/"
SCORER = "https://raw.githubusercontent.com/Vrin-cloud/supersede/677993d3713c265329ac935262d3c08cbfa4cd63/src/supersede/reward.py"
INPUTS = {
    "train.jsonl": (
        DATA + "train.jsonl",
        "4a9f5523fbdf06a88d375c0a7ebb7525398b719f096260a69735a8db78239820",
    ),
    "test.jsonl": (
        DATA + "test.jsonl",
        "012f9a5be2808a2adb4fb107e594ae648078090cc8564ee42fd51ebc8ea477c2",
    ),
    "reward.py": (
        SCORER,
        "3cc03c858613a3055a67c4d019d61990258bdd492f49a1ff96d44c3f5ea8a249",
    ),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    out = parser.parse_args().out
    out.mkdir(exist_ok=True, parents=True)
    for name, (url, expected) in INPUTS.items():
        path = out / name
        if path.exists():
            data = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=90) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Digest mismatch for {name}")
        if not path.exists():
            path.write_bytes(data)
        print(name, expected)
