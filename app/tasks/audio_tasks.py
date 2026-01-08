from __future__ import annotations

from pathlib import Path

from celery.exceptions import Ignore

from app.workflows.config import settings
from app.audio import audio_db, audio_job_db
from app.audio.pipeline import run_audio_ingest_pipeline
from app.rag.chroma_admin import delete_by_audio_id
from app.audio.celery_app import celery_app
#todo 完整的音频处理 Celery 任务实现，把 控制平面（任务状态、取消、进度） 和 数据平面（音频处理、ASR、向量化）

#todo它在“发现用户请求取消时”，立刻把任务状态改成“已取消”，然后强行中断当前任务的执行。   IO = 钱（不可避免的成本）CPU = 工人,线程 / 协程 = 工位，同步 / 异步 = 花钱方式
def _check_cancel(job_id: str):
    if audio_job_db.is_cancel_requested(job_id):                # 看取消请求是不是1
        audio_job_db.mark_cancelled(job_id)                     # 数据库先变取消
        raise Ignore()                                          # 取消当前的任务执行，新版本可能有更好写法

#todo它是一个「可恢复、可中断、可追踪的后台任务」
# 这是一个不可信环境下执行的 IO 密集任务
# 所以你给它配了：
#   自动重试（IO / OS / 网络不可信）
#   指数退避 + 抖动（防止雪崩）
#   最大重试次数（止损）
@celery_app.task(
    name="app.tasks.audio_tasks.audio_ingest_task",
    bind=True,
    autoretry_for=(Exception,),                                 # 只要出现异常都会触发自动重试，这个异常不要太宽泛
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},)
def audio_ingest_task(self, job_id: str, audio_id: str):
                                                                                        #todo 这一步是 控制平面（control plane）它们不参与计算结果 只决定：要不要做、怎么做、做到什么程度这三行代码不是“读配置”，而是在“建立任务的执行合同（execution contract）”。
    flags = audio_job_db.get_job_flags(job_id)                                          #todo flags包含如下列overwrite是否覆盖旧结果？, delete_old_file新任务成功后旧文件是否删除？, old_stored_path旧文件在哪里？, cancel_requested这个任务要不要继续？
    old_path = flags.get("old_stored_path")                                             #todo 把“旧资源的引用”保存下来，以备任务成功后使用。如果要删，删哪一个
    delete_old_file = bool(int(flags.get("delete_old_file", 0) or 0))                   #todo 要不要删
    audio_job_db.update_job(job_id, status="running", progress=1, message="starting")   #todo 控制元数据，让任务开始，进度为1（乱写的）这一行相当于“进度条初始化”，告诉系统任务开始了，但不代表算法或 IO 的实际完成百分比
    audio_db.update_audio_status(audio_id, status="running")                            #todo 是“把资源标记为正在处理”，让系统知道这个音频正在被占用或修改，同时和任务状态同步”。
    _check_cancel(job_id)                                                               #todo 如果前台在这个期间发出了取消请求，我们这里才会真正取消
                                                                                        #todo 数据平面
    doc = audio_db.get_audio_document(audio_id)                                         #todo 是任务的数据入口，是后续所有音频处理操作的起点，同时也是防御式编程的第一个检查点。
    # doc是取这个音频文件在数据库中这一行的全部信息
    if not doc:                                                                         #todo 判断任务是否能继续
        raise RuntimeError("audio_document not found")                                  #todo 立即中断任务，触发状态更新 / retry
                                                                                        #todo 这两行代码的作用是：验证任务数据边界是否有效，一旦不存在音频记录就立即中断任务，保证系统不会在无效输入上浪费资源或崩溃。
    raw_path = Path(doc["stored_path"])                                                 #todo 建立文件对象，准备 IO 操作
    # 存储路径如果不存在也抛出异常
    if not raw_path.exists():
        raise RuntimeError("stored audio file missing")
                                                                                        #todo 这一段的作用是“建立任务的文件输入边界并验证其存在性”，防止后续音频处理在不存在的文件上浪费资源或崩溃”，是典型的防御式编程和可控 IO 操作。
    audio_job_db.update_job(job_id, progress=5, message="cleaning old vectors")         #todo 更新任务进度 / 提供可观测 checkpoint
    delete_by_audio_id(audio_id)                                                        #todo 清空向量数据库中这个音频id相关内容

    _check_cancel(job_id)                                                               #todo 检测任务是否被取消，确保资源不浪费

    audio_job_db.update_job(job_id, progress=10, message="transcribing/indexing")
    res = run_audio_ingest_pipeline(                            #todo真正执行文件处理、切割、ASR、向量化等操作
        audio_id=audio_id,                                      #音频任务 ID，用于关联数据库
        raw_path=raw_path,                                      #文件系统路径，音频源文件
        original_filename=doc["original_filename"],             #原始上传文件名（用于记录或日志）
        visibility=doc["visibility"],                           #可见性控制，决定数据访问权限
        language=doc.get("language"),                           #语言信息，可影响 ASR 模型选择
        wav_dir=Path(settings.audio_wav_dir),                   #转换后的 WAV 文件存放目录
    )                                                           #todo 调用流水线真正的做文件上传处理，切割等等操作这一段代码的作用是：先报告任务进度进入核心处理阶段，然后调用流水线处理音频，实现真正的数据平面操作（上传 / 切割 / ASR / 向量化 / 索引）。控制平面和数据平面交替出现，保证任务可控、可观察、可取消。

    _check_cancel(job_id)

    audio_db.update_audio_indexed(
        audio_id=audio_id,                                      #标识音频记录
        duration_ms=int(res["duration_ms"]),                    #音频时长，整型
        language=res.get("language"),                           #ASR 检测出的语言
        segment_count=int(res["segments"]),                     #切割后的音频片段数量
        status="indexed",                                       #标记音频处理完成，可以被查询或索引
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