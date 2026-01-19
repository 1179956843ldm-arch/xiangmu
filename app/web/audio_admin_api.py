from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from app.web.auth_api import UserInDB, get_current_user
from app.audio.celery_app import celery_app
from app.service.rbac_service import check_permission

from app.audio import audio_db, audio_job_db
from app.rag.chroma_admin_audio import (
    delete_many_audio_ids,
    update_visibility_by_audio_id,
    reset_audio_collection,
)
from app.workflows.config import settings

from app.model.audio_admin_model import (
    AudioDocListResp,
    AudioSegmentsResp,
    AudioTranscriptResp,
    AudioStatsResp,
    UpdateVisibilityReq,
    UpdateVisibilityResp,
    BulkDeleteReq,
    BulkDeleteResp,
    BulkReindexReq,
    BulkReindexResp,
    ReindexItem,
    ResetAudioCollectionResp,
)

router = APIRouter(prefix="/audio/admin", tags=["audio-admin"])


def _require_manage_docs(user: UserInDB) -> None:
    """
    权限检查
    """
    check_permission(user, "kb.manage_docs")


def _normalize_visibility(v: str) -> str:
    """“
    规范化可见性字段”函数，用来确保传入的 visibility 值合法，
    """
    v = (v or "").strip().lower()#把字符串里的所有字母转换成小写。
    if v in ("public", "internal"):
        return v
    raise HTTPException(status_code=400, detail="visibility must be public/internal")


@router.get("/stats", response_model=AudioStatsResp)

def stats(current_user: UserInDB = Depends(get_current_user)):
    """
    获取音频统计信息接口
    """
    _require_manage_docs(current_user)
    s = audio_db.audio_stats()
    return AudioStatsResp(**s)


@router.get("/docs", response_model=AudioDocListResp)

def list_docs(
    q: Optional[str] = Query(default=None),                         #搜索关键词（可选）
    visibility: Optional[str] = Query(default=None),                #可见性过滤（public/internal，可选）
    status: Optional[str] = Query(default=None),                    #状态过滤（active/inactive，可选）
    uploader_user_id: Optional[int] = Query(default=None),          #上传者 ID 过滤（可选）
    page: int = Query(default=1, ge=1),                             #页码，默认为 1，最小值 1
    page_size: int = Query(default=20, ge=1, le=100),               #每页大小，默认 20，范围 1~100
    current_user: UserInDB = Depends(get_current_user),             #通过依赖注入获取当前登录用户
):
    """
    获取音频文档列表
    """
    _require_manage_docs(current_user)
    total, items = audio_db.list_audio_documents(
        q=q,
        visibility=visibility,
        status=status,
        uploader_user_id=uploader_user_id,
        page=page,
        page_size=page_size,
    )
    return AudioDocListResp(total=total, page=page, page_size=page_size, items=items)


@router.get("/docs/{audio_id}/segments", response_model=AudioSegmentsResp)

def get_segments(
    audio_id: str,
    limit: int = Query(default=2000, ge=1, le=5000),
    current_user: UserInDB = Depends(get_current_user),
):
    """
    获取单个音频文档的分段信息接口
    """
    _require_manage_docs(current_user)
    doc = audio_db.get_audio_document(audio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")
    items = audio_db.list_audio_segments(audio_id, limit=limit)#获取音频分段
    return AudioSegmentsResp(audio_id=audio_id, items=items)


@router.get("/docs/{audio_id}/transcript", response_model=AudioTranscriptResp)
def get_transcript(
    audio_id: str,
    max_segments: int = Query(default=5000, ge=1, le=5000),
    current_user: UserInDB = Depends(get_current_user),
):
    """
    获取音频文档全文转录文本接口
    """
    _require_manage_docs(current_user)
    doc = audio_db.get_audio_document(audio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")
    t = audio_db.get_audio_transcript(audio_id, max_segments=max_segments)
    return AudioTranscriptResp(audio_id=audio_id, transcript=t)


@router.patch("/docs/{audio_id}/visibility", response_model=UpdateVisibilityResp)
def set_visibility(
    audio_id: str,
    req: UpdateVisibilityReq,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    修改音频文档可见性接口
    """
    _require_manage_docs(current_user)

    doc = audio_db.get_audio_document(audio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    v = _normalize_visibility(req.visibility)
    audio_db.update_audio_visibility(audio_id, v)

    vectors = update_visibility_by_audio_id(audio_id, v)

    return UpdateVisibilityResp(audio_id=audio_id, visibility=v, vectors_updated=int(vectors))


@router.post("/docs/bulk-delete", response_model=BulkDeleteResp)
def bulk_delete(
    req: BulkDeleteReq,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    批量删除音频文档接口
    """
    _require_manage_docs(current_user)

    audio_ids = [a.strip() for a in (req.audio_ids or []) if (a or "").strip()]
    if not audio_ids:
        raise HTTPException(status_code=400, detail="audio_ids is empty")

    vectors_deleted = delete_many_audio_ids(audio_ids)

    deleted: List[str] = []
    missing: List[str] = []
    files_deleted: List[str] = []

    for aid in audio_ids:
        doc = audio_db.get_audio_document(aid)
        if not doc:
            missing.append(aid)
            continue

        try:
            audio_db.delete_audio_segments(aid)
        except Exception:
            pass

        audio_db.delete_audio_document(aid)
        deleted.append(aid)

        if req.delete_files:
            try:
                p = Path(str(doc.get("stored_path") or ""))
                if p.exists() and p.is_file():                         #exists()判断当前 Path 对象对应的文件或目录是否存在       is_file()判断当前 Path 对象是否是一个 普通文件（regular file）
                    p.unlink()                                         #删除当前 Path 对象对应的文件或符号链接（symlink）
                    files_deleted.append(aid)
            except Exception:
                pass

    return BulkDeleteResp(
        deleted=deleted,
        missing=missing,
        vectors_deleted=vectors_deleted,
        files_deleted=files_deleted,
    )


@router.post("/docs/bulk-reindex", response_model=BulkReindexResp)
def bulk_reindex(
    req: BulkReindexReq,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    批量重新索引音频文档接口
    """
    _require_manage_docs(current_user)

    audio_ids = [a.strip() for a in (req.audio_ids or []) if (a or "").strip()]
    if not audio_ids:
        raise HTTPException(status_code=400, detail="audio_ids is empty")

    submitted: List[ReindexItem] = []
    skipped_running: List[str] = []
    missing: List[str] = []

    for aid in audio_ids:
        doc = audio_db.get_audio_document(aid)
        if not doc:
            missing.append(aid)
            continue

        if audio_db.is_audio_running(aid):
            skipped_running.append(aid)
            continue

        job_id = f"job-reindex-{aid}"
        audio_job_db.create_job(job_id, aid, overwrite=False, delete_old_file=False, old_stored_path=None)

        audio_db.update_audio_status(aid, "queued")

        async_result = celery_app.send_task(
            "app.tasks.audio_tasks.audio_reindex_task",
            args=[job_id, aid],
            queue=getattr(settings, "celery_audio_queue", "audio"),
        )
        audio_job_db.bind_task(job_id, async_result.id)

        submitted.append(
            ReindexItem(
                audio_id=aid,
                job_id=job_id,
                celery_task_id=async_result.id,
                status_url=f"/audio/jobs/{job_id}",
            )
        )

    return BulkReindexResp(submitted=submitted, skipped_running=skipped_running, missing=missing)


@router.post("/chroma/reset", response_model=ResetAudioCollectionResp)
def reset_audio_chroma(
    confirm: str = Query(..., description="必须等于 DELETE_AUDIO_COLLECTION 才会执行"),
    current_user: UserInDB = Depends(get_current_user),
):
    """
    重置 Chroma 音频向量集合接口
    """
    _require_manage_docs(current_user)

    if confirm != "DELETE_AUDIO_COLLECTION":
        raise HTTPException(status_code=400, detail="confirm mismatch")

    reset_audio_collection()
    return ResetAudioCollectionResp(ok=True, collection=settings.audio_collection_name)