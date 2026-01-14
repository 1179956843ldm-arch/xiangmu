from __future__ import annotations
from typing import Iterable
from app.rag.chroma import collection, delete_where_and_count, delete_collection_by_name
from app.workflows.config import settings


def get_audio_collection():
    return collection(settings.audio_collection_name)


def get_ids_and_metadatas_by_audio_id(audio_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    col = get_audio_collection()
    got = col.get(where={"audio_id": audio_id}, include=["metadatas"])
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    return list(ids), list(metas)


def delete_by_audio_id(audio_id: str) -> int:
    #todo 删除向量库里
    # audio_id == xxx
    # 的所有记录，并返回删除条数
    col = get_audio_collection()
    #todo get_audio_collection()
    # → 拿到音频# segment向量所在的collection / index
    return delete_where_and_count(col, {"audio_id": audio_id})
    #todo {"audio_id": audio_id}
    # → 删除条件（where filter）
    # delete_where_and_count(...)
    # → 真正执行删除，并返回删除数量


def update_visibility_by_audio_id(audio_id: str, visibility: str) -> int:
    col = get_audio_collection()
    ids, metas = get_ids_and_metadatas_by_audio_id(audio_id)
    if not ids:
        return 0

    new_metas: list[dict[str, Any]] = []
    for m in metas:
        mm = dict(m or {})
        mm["visibility"] = visibility
        new_metas.append(mm)

    col.update(ids=ids, metadatas=new_metas)
    return len(ids)


def delete_many_audio_ids(audio_ids: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for aid in audio_ids:
        aid = (aid or "").strip()
        if not aid:
            continue
        out[aid] = delete_by_audio_id(aid)
    return out


def reset_audio_collection() -> None:
    delete_collection_by_name(settings.audio_collection_name)
    collection.cache_clear()
    get_audio_collection()
