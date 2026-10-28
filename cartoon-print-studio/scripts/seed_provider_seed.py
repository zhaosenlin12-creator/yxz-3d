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


def provider_entry(keys: dict[str, str], *labels: str) -> dict[str, object]:
    """Build a provider config that carries every key of a family.

    ``apiKey`` holds the first key only: the provider validators send that
    field as-is, and a comma separated list would be rejected as an invalid
    credential. The remaining keys go into ``apiKeys``, where the frontend
    picks them up to rotate when one of them runs out of quota.
    """
    found = [keys[label].strip() for label in labels if keys.get(label)]
    if not found:
        return {}
    return {"apiKey": found[0], "apiKeys": found}


def main() -> int:
    keys = read_keys(KEYFILE)
    if not keys:
        print(f"[seed] no keys found in {KEYFILE}", file=sys.stderr)
        return 1

    # Same order as gen-provider-bootstrap.ps1: the primary key first, the
    # spare one behind it. A rate limited primary is picked up by the
    # frontend's key rotation, but the validators use the primary directly.
    minimax = provider_entry(keys, "minimax-key", "minimax-key-2")
    deepseek = keys.get("deepseek-key", "")

    seed = {
        "override": True,
        # `override` only replaces stale *credentials* in the browser with the
        # current keys. The speech provider and the voice are picked by hand
        # in the settings, so they must survive a reload: only a seed that
        # really wants to move the voice sets this flag.
        "speechOverride": False,
        "providers": {
            "minimax": {
                **minimax,
                "baseUrl": "https://api.minimaxi.com/v1/",
            },
            "minimax-audio-speech": {
                **minimax,
                "baseUrl": "https://api.minimaxi.com/v1/",
            },
            "deepseek": {
                "apiKey": deepseek,
                "baseUrl": "https://api.deepseek.com",
            },
            # The local voice pack (Voicebox / Qwen CustomVoice). The voice
            # itself is not seeded: the frontend discovers the sound profiles
            # from http://127.0.0.1:17493/profiles and keeps the one the user
            # picked in settings/speech/voice.
            "voicebox-local": {
                "baseUrl": "http://127.0.0.1:17493",
                "model": "qwen-custom-voice-1.7B",
                "modelSize": "1.7B",
                "instruct": "温暖、活泼、亲切，带一点可爱的卡通感，语速自然，像宜小智在和用户面对面交流。",
            },
        },
        "activeProvider": "minimax",
        "activeModel": "MiniMax-M2.7",
        "speech": {
            # The local voice pack goes first because it does not depend on a
            # network round trip; MiniMax is the cloud backup for when the
            # local service is not running.
            "provider": "voicebox-local",
            "model": "qwen-custom-voice-1.7B",
            "fallbacks": [
                {
                    "providerId": "minimax-audio-speech",
                    "model": "speech-2.5-hd",
                    "voice": "female-shaonv",
                }
            ],
        },
    }

    os.makedirs(os.path.dirname(SEED), exist_ok=True)
    with open(SEED, "w", encoding="utf-8") as handle:
        json.dump(seed, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"[seed] wrote {SEED}")
    print("[seed] minimax chat keys:", ", ".join(l for l in ("minimax-key", "minimax-key-2") if keys.get(l)))
    print("[seed] deepseek key:", "present" if deepseek else "missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
