from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

import chromadb

from app.workflows.config import settings

@lru_cache(maxsize=1)
def client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


@lru_cache(maxsize=8)
def collection(name: str):
    return client().get_or_create_collection(name)


def delete_collection_by_name(name: str) -> None:
    c = client()
    c.delete_collection(name=name)

def delete_where_and_count(col, where: dict[str, Any]) -> int:
    try:
        got = col.get(where=where)
        ids = got.get("ids") or []
        if ids:
            col.delete(ids=ids)
        return int(len(ids))
    except Exception:
        return 0



