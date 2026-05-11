"""File-based JSON cache with per-key TTL."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Awaitable

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def get(key: str, ttl_seconds: int) -> Any | None:
    p = _path(key)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - raw.get("ts", 0) > ttl_seconds:
        return None
    return raw.get("data")


def put(key: str, data: Any) -> None:
    p = _path(key)
    p.write_text(json.dumps({"ts": time.time(), "data": data}))


async def cached(key: str, ttl_seconds: int, fetcher: Callable[[], Awaitable[Any]]) -> Any:
    hit = get(key, ttl_seconds)
    if hit is not None:
        return hit
    data = await fetcher()
    put(key, data)
    return data
