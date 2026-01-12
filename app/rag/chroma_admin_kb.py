from __future__ import annotations
from typing import Any
from app.rag.chroma import collection, delete_where_and_count, delete_collection_by_name
from app.workflows.config import settings


def get_kb_collection():
    return collection(settings.collection_name)


def get_collection():
    return get_kb_collection()


def get_ids_and_metadatas_by_doc_id(doc_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    col = get_kb_collection()
    got = col.get(where={"doc_id": doc_id}, include=["metadatas"])
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    return list(ids), list(metas)


def count_by_doc_id(doc_id: str) -> int:
    ids, _ = get_ids_and_metadatas_by_doc_id(doc_id)
    return len(ids)


def delete_by_doc_id(doc_id: str) -> int:
    col = get_kb_collection()
    return delete_where_and_count(col, {"doc_id": doc_id})


def update_visibility_by_doc_id(doc_id: str, visibility: str) -> int:
    col = get_kb_collection()
    ids, metas = get_ids_and_metadatas_by_doc_id(doc_id)
    if not ids:
        return 0

    new_metas: list[dict[str, Any]] = []
    for m in metas:
        mm = dict(m or {})
        mm["visibility"] = visibility
        new_metas.append(mm)

    col.update(ids=ids, metadatas=new_metas)
    return len(ids)


def reset_kb_collection() -> None:
    delete_collection_by_name(settings.collection_name)
    collection.cache_clear()
    get_kb_collection()
