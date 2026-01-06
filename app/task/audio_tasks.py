from __future__ import annotations

from pathlib import Path

from celery.exceptions import Ignore

from app.workflows.config import settings
from app.db import audio_db
from app.db import audio_job_db
from app.pipeline import run_audio_ingest_pipeline
from app.rag.chroma_admin import delete_by_audio_id
from app.celery_app import celery_app

def _check_cancel(job_id: str):
    if audio_job_db.is_cancel_requested(job_id):  # 看取消请求是不是1
        audio_job_db.mark_cancelled(job_id)  # 数据库先变取消
        raise Ignore()  # 取消当前的任务执行，新版本可能有更好写法


@celery_app.task(
    name="app.tasks.audio_tasks.audio_ingest_task",
    bind=True,
    autoretry_for=(Exception,),  # 只要出现异常都会触发自动重试，这个异常不要太宽泛
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},)
def audio_ingest_task(self, job_id: str, audio_id: str):
    flags = audio_job_db.get_job_flags(job_id)
    # flags包含如下列overwrite, delete_old_file, old_stored_path, cancel_requested
    old_path = flags.get("old_stored_path")
    delete_old_file = bool(int(flags.get("delete_old_file", 0) or 0))

    audio_job_db.update_job(job_id, status="running", progress=1, message="starting")
    # 控制元数据，让任务开始，进度为1（乱写的）
    audio_db.update_audio_status(audio_id, status="running")

    _check_cancel(job_id)  # 如果前台在这个期间发出了取消请求，我们这里才会真正取消

    doc = audio_db.get_audio_document(audio_id)
    # doc是取这个音频文件在数据库中这一行的全部信息
    if not doc:
        raise RuntimeError("audio_document not found")

    raw_path = Path(doc["stored_path"])
    # 存储路径如果不存在也抛出异常
    if not raw_path.exists():
        raise RuntimeError("stored audio file missing")

    audio_job_db.update_job(job_id, progress=5, message="cleaning old vectors")
    delete_by_audio_id(audio_id)  # 清空向量数据库中这个音频id相关内容

    _check_cancel(job_id)

    audio_job_db.update_job(job_id, progress=10, message="transcribing/indexing")
    res = run_audio_ingest_pipeline(
        audio_id=audio_id,
        raw_path=raw_path,
        original_filename=doc["original_filename"],
        visibility=doc["visibility"],
        language=doc.get("language"),
        wav_dir=Path(settings.audio_wav_dir),
    ) # 调用流水线真正的做文件上传处理，切割等等操作

    _check_cancel(job_id)

    audio_db.update_audio_indexed(
        audio_id=audio_id,
        duration_ms=int(res["duration_ms"]),
        language=res.get("language"),
        segment_count=int(res["segments"]),
        status="indexed",
    )

    audio_job_db.update_job(job_id, status="succeeded", progress=100, message=f"indexed {res['segments']} segments")

    # 新的文件已经处理好，旧的可以删除了
    if delete_old_file and old_path and old_path != str(raw_path):
        try:
            p = Path(str(old_path))
            if p.exists() and p.is_file():
                p.unlink()
        except Exception:
            # 应该记录日志
            print('注意异常！！！！！！！！！！！！！！！！1')

    return res