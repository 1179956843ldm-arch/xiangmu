from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field
#todo 你这段代码是 Pydantic 模型定义，主要用于音频管理系统的 API 请求/响应序列化和验证。它定义了多种与音频相关的数据结构。

class AudioIngestResp(BaseModel):
    audio_id: str
    stored_as: str
    duration_ms: int
    language: Optional[str] = None
    visibility: str
    segments: int


class AudioDocDetail(BaseModel):
    audio_id: str
    original_filename: str
    stored_path: str
    duration_ms: int
    language: Optional[str] = None
    visibility: str
    status: str
    segment_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AudioSearchHit(BaseModel):
    audio_id: str
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    score: Optional[float] = None  # 向量库有些返回不了score就留空
    clip_url: Optional[str] = None  # ⚠️加这行就行


class AudioSearchResp(BaseModel):
    q: str
    k: int
    allowed_visibilities: List[str]
    hits: List[AudioSearchHit]

class AudioIngestAsyncResp(BaseModel):
    job_id: str
    audio_id: str
    stored_as: str
    visibility: str
    celery_task_id: Optional[str] = None
    status_url: str

class AudioJobResp(BaseModel):
    job_id: str
    audio_id: str
    celery_task_id: Optional[str] = None
    status: str
    progress: int
    message: Optional[str] = None
    cancel_requested: int = 0
    overwrite: int = 0
    delete_old_file: int = 0
    old_stored_path: Optional[str] = None
    cancelled_at: Optional[Any] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None