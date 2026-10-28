"""Regenerate ``airi/apps/stage-web/public/provider-seed.json`` from ``keys.txt``.

The seed file is git-ignored and holds the only copy of the credentials the
browser needs (the AIRI frontend talks to MiniMax / DeepSeek directly). This
script keeps it in sync with ``keys.txt`` so a rotated or topped-up key only
has to be written once.

Usage (from the repository root):

    cartoon-print-studio/ai/forge-webui/venv/Scripts/python.exe \
        cartoon-print-studio/scripts/seed_provider_seed.py

Keys are ordered by priority: the first usable key of a family comes first,
the remaining ones are appended so the frontend can fall back to them when a
key runs out of quota.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
KEYFILE = os.path.join(ROOT, "keys.txt")
SEED = os.path.join(REPO, "airi", "apps", "stage-web", "public", "provider-seed.json")


def read_keys(path: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    if not os.path.isfile(path):
        return keys

    with open(path, encoding="utf-8") as handle:
        for line in handle.read().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or (":" not in line and "\uff1a" not in line):
                continue
            label, value = re.split(r"[:\uff1a]\s*", line, maxsplit=1)
            value = value.strip()
            if value:
                keys[label.strip()] = value
    return keys


def join_keys(keys: dict[str, str], *labels: str) -> str:
    """Resolve the given key labels and join them into one provider field.

    The frontend accepts a comma separated key list and tries them one after
    another, so a key that ran out of quota does not take the app down.
    """
    return ",".join(keys[label] for label in labels if keys.get(label))


def main() -> int:
    keys = read_keys(KEYFILE)
    if not keys:
        print(f"[seed] no keys found in {KEYFILE}", file=sys.stderr)
        return 1

    minimax = join_keys(keys, "minimax-key-2", "minimax-key")
    deepseek = keys.get("deepseek-key", "")

    seed = {
        "override": True,
        "providers": {
            "minimax": {
                "apiKey": minimax,
                "baseUrl": "https://api.minimaxi.com/v1/",
            },
            "minimax-audio-speech": {
                "apiKey": minimax,
                "baseUrl": "https://api.minimaxi.com/v1/",
            },
            "deepseek": {
                "apiKey": deepseek,
                "baseUrl": "https://api.deepseek.com",
            },
        },
        "activeProvider": "minimax",
        "activeModel": "MiniMax-M2.7",
        "speech": {
            "provider": "minimax-audio-speech",
            "model": "speech-2.5-hd",
            "voice": "female-shaonv",
        },
    }

    os.makedirs(os.path.dirname(SEED), exist_ok=True)
    with open(SEED, "w", encoding="utf-8") as handle:
        json.dump(seed, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"[seed] wrote {SEED}")
    print("[seed] minimax chat keys:", ", ".join(l for l in ("minimax-key-2", "minimax-key") if keys.get(l)))
    print("[seed] deepseek key:", "present" if deepseek else "missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
