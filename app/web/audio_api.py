from __future__ import annotations

import json
import time, uuid
from pathlib import Path
from typing import List, Optional, Any, Iterable

from fastapi import (APIRouter,
                     BackgroundTasks,
                     Depends,
                     File,
                     Form,
                     HTTPException,
                     Query,
                     Request,
                     UploadFile,)
from fastapi.responses import FileResponse,StreamingResponse
from langchain_core.messages import SystemMessage, HumanMessage


from app.es.es_audio_admin import reset_audio_index
from app.web.auth_api import UserInDB, get_current_user
from app.audio.audio_tool import clip_audio_to_mp3
from app.workflows.config import settings
from app.audio import audio_db, audio_job_db
from app.workflows.deps import get_audio_vs, get_llm
from app.model.audio_model import (AudioIngestAsyncResp,
                                   AudioJobResp,
                                   AudioDocDetail,
                                   AudioSearchResp,
                                   AudioSearchHit,
                                   AudioAskResp,
                                   AudioCitation,
                                   AudioAskReq)
from app.service.rbac_service import allowed_kb_visibilities, check_permission
from app.tasks.audio_tasks import audio_ingest_task, audio_reindex_task
from app.rag.chroma_admin_audio import delete_by_audio_id
router = APIRouter(prefix="/audio", tags=["audio"])

AUDIO_DIR = Path(getattr(settings, "audio_dir", "data/audio"))
CLIP_DIR = Path(getattr(settings, "audio_clip_dir", "data/audio_clips"))
WAV_DIR = Path(getattr(settings,"audio_wav_dir","data/audio_wav"))

def _require_manage_docs(user: UserInDB) -> None:
    """"
    _require_manage_docs = “强制要求用户拥有 kb.manage_docs 权限，否则立刻拒绝”
    它不返回值，只做一件事：
    👉 不满足就抛异常
    """
    check_permission(user, "kb.manage_docs")


def _normalize_visibility(v: str) -> str:
    """
    把用户输入的 visibility 做“安全归一化”，只允许白名单值，其余全部降级为 public。
    """
    v = (v or "").strip().lower()
    return v if v in ("public", "internal") else "public"

def _get_allowed_and_check(user: UserInDB, doc_visibility: Optional[str] = None) -> List[str]:
    """
    统一计算「用户可访问的音频可见性集合」，并在需要时对某个具体文档做权限校验。
        1 算出“这个用户能看到哪些 visibility”
        2（可选）顺手校验：某个具体文档能不能看
        3 返回 allowed 列表，供后续检索使用
    """
    perms = getattr(user, "permissions", None)
    allowed = allowed_kb_visibilities(perms)
    if "public" not in allowed:
        allowed = ["public"] + [x for x in allowed if x != "public"]

    if doc_visibility:
        vis = (doc_visibility or "").strip().lower()
        if vis not in set(allowed):
            raise HTTPException(status_code=403, detail="no permission to access this audio")

    return allowed

def _get_allowed_set(user: UserInDB) -> set[str]:
    """
    _get_allowed_set = 为“热路径权限判断”准备的set版本可见性集合热路径（HotPath）：👉 在系统运行中被“非常频繁执行”的代码路径
    _get_allowed_set 执行流程
       │
       ├─ 调用 _get_allowed_and_check(user)
       │     └─ 完成权限校验 + 可见性计算
       ├─ 将返回的 allowed visibilities 转为 set
       │     └─ 用于高频 contains 判断（O(1)）
       └─ 返回 allowed_set
    """

    return set(_get_allowed_and_check(user))

def _compute_allowed_visibilities(user: UserInDB) -> List[str]:
    """
    计算“当前用户最终允许访问的音频可见性列表”并强制保证 public 一定在其中（且排在最前）。
    _compute_allowed_visibilities 执行流程
     │
     ├─ 从 User 对象中读取 permissions
     ├─ 根据权限映射出可访问的知识库可见性列表
     ├─ 强制保证 "public" 一定存在
     │     └─ 且始终排在列表最前（作为默认兜底）
     └─ 返回最终 allowed visibilities
     """

    perms = getattr(user, "permissions", None)
    allowed = allowed_kb_visibilities(perms)
    if "public" not in allowed:
        allowed = ["public"] + [x for x in allowed if x != "public"]
    return allowed


def _ensure_can_access_visibility(user: UserInDB, doc_visibility: str) -> List[str]:
    """
    _ensure_can_access_visibility = 对单个音频文档的可见性做强制访问校验（硬闸）
    _ensure_can_access_visibility 执行流程
      │
      ├─ 计算用户可访问的 visibility 列表
      ├─ 规范化目标文档 visibility（lower + strip）
      ├─ 校验 visibility 是否在允许范围内
      │     └─ 否则抛出 403
      └─ 返回 allowed visibilities
      """
    allowed = _compute_allowed_visibilities(user)
    vis = (doc_visibility or "").strip().lower()
    if vis not in set(allowed):
        raise HTTPException(status_code=403, detail="no permission to access this audio")
    return allowed


def _absolute_base(request: Request) -> str:
    """
     _absolute_base = 生成当前请求上下文下的绝对 URL 前缀
     _absolute_base 执行流程
      │
      ├─ 从 Request 中读取 base_url
      ├─ 转换为字符串
      ├─ 去除末尾斜杠（rstrip("/")）
      └─ 返回标准化的绝对 URL 前缀
      """

    return str(request.base_url).rstrip("/")

def _clip_url(base: str, audio_id: str, start_ms: int, end_ms: int) -> str:
    """
    _clip_url = 将音频片段定位信息转换为可回放的 clip HTTP URL
    _clip_url 执行流程
      │
      ├─ 接收 base（请求绝对地址前缀）
      ├─ 接收 audio_id / start_ms / end_ms
      ├─ 拼接 clip 接口路径
      └─ 返回可访问的音频裁剪 URL
      """

    return f"{base}/audio/docs/{audio_id}/clip?start_ms={start_ms}&end_ms={end_ms}"

def _build_langchain_messages(messages: list[dict[str, str]]):
    """
    _build_langchain_messages = 业务 message → LangChain SDK 消息适配层
    _build_langchain_messages 执行流程
      │
      ├─ 遍历自定义 messages 列表
      ├─ 读取 role / content 字段
      ├─ role == "system"
      │     └─ 构造 SystemMessage
      ├─ 否则
      │     └─ 构造 HumanMessage
      ├─ 收集为 LangChain 消息对象列表
      └─ 返回 msg_objs
    将我们自己构造的message转换成langchain能识别的消息对象列表，是一个小的工具类
    这里的message本意是这样的
    [
        {"role": "system", "content": "你是一个音频问答助手。"},
        {"role": "user", "content": "请根据音频内容回答问题。"}
    ]
    """
    msg_objs = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        msg_objs.append(
            SystemMessage(content=content) if role == "system" else HumanMessage(content=content)
        )
    return msg_objs

def _openai_chat_complete(*, messages: list[dict[str, str]]) -> str:
    """
    _openai_chat_complete = 同步 LLM 调用 → 返回最终文本答案
    _openai_chat_complete 执行流程
      │
      ├─ 获取 LLM 实例（get_llm）
      ├─ 将 messages 转换为 LangChain 消息格式
      ├─ 调用 llm.invoke() 发起同步推理
      ├─ 提取返回内容（result.content）
      ├─ 做基础清洗（strip）
      └─ 异常统一转换为 HTTP 500
    """

    llm = get_llm()
    try:
        result = llm.invoke(_build_langchain_messages(messages))
        return (result.content or "").strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用出错: {e}")

def _openai_stream(*, messages: list[dict[str, str]]) -> Iterable[str]:
    """
    _openai_stream = LLM → token/chunk 流 → Python generator
    _openai_stream 执行流程
      │
      ├─ 获取 LLM 实例（get_llm）
      ├─ 将 messages 转换为 LangChain 消息格式
      ├─ 调用 llm.stream() 启动流式生成
      ├─ 逐 chunk 接收模型输出
      │     └─ 有内容则 yield 给上层
      ├─ 上层通过 yield 实现 SSE / 流式响应
      └─ 异常统一转换为 HTTP 500
    参数和之前的一样，返回值是Iterable[str]，主要我们后面用yield流式输出做好基础
    """
    llm = get_llm()
    try:
        for chunk in llm.stream(_build_langchain_messages(messages)):
            if chunk.content:
                yield chunk.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 流式调用出错: {e}")

def _build_rag_messages(question: str, citations: list[AudioCitation], system_prompt: Optional[str]) -> list[
    dict[str, str]]:
    """
     _build_rag_messages = 把「音频检索结果」转成「受约束的 LLM 输入上下文」
     _build_rag_messages 执行流程
      │
      ├─ 确定 system prompt
      │     ├─ 优先使用自定义 system_prompt
      │     └─ 否则使用默认「基于音频片段回答」约束提示
      ├─ 遍历 citations 构造上下文片段文本
      │     └─ 标注序号 [1][2]... + 音频元信息
      ├─ 拼接完整上下文（ctx）
      ├─ 构造 user prompt
      │     ├─ 用户问题
      │     ├─ 音频片段上下文
      │     └─ 明确回答约束（仅用片段 / 禁止编造 / 引用标注）
      ├─ 封装为 ChatCompletion messages 结构
      │     ├─ system
      │     └─ user
      └─ 返回 messages 列表
    """

    sys = (system_prompt or "").strip() or (
        "你是企业知识库助手，回答必须基于给定的【音频片段】内容。"
        "如果片段不足以回答，就明确说“不确定/片段中没有”。"
        "回答要简洁，并在结尾给出引用列表（用 [1][2]... 标注）。"
    )

    ctx_lines = [
        f"[{i}] audio_id={c.audio_id} segment_id={c.segment_id} "
        f"start_ms={c.start_ms} end_ms={c.end_ms}\n片段文本：{c.text}"
        for i, c in enumerate(citations, start=1)
    ]
    ctx = "\n\n".join(ctx_lines) if ctx_lines else "（无片段）"

    user = (
        f"问题：{question}\n\n"
        f"【音频片段】\n{ctx}\n\n"
        "要求：\n1) 只用片段信息回答。\n"
        "2) 如果引用了某个片段，请用 [序号] 标注。\n"
        "3) 不要编造片段里没有的信息。"
    )

    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]

def _search_audio_segments(vs, query: str, allowed_vis: list[str], k: int, audio_id: Optional[str] = None):
    """
    _search_audio_segments = 带权限过滤的“高召回”音频向量检索函数
    _search_audio_segments 执行流程
      │
      ├─ 构造向量检索过滤条件（visibility ∈ allowed_vis）
      ├─ 可选追加 audio_id 精确过滤
      ├─ 计算 fetch_k（扩大召回窗口）
      │     └─ fetch_k = min(max(k * 5, k), 50)
      ├─ 调用向量库 similarity_search_with_score
      └─ 返回（doc, score）列表
      """

    where = {"visibility": {"$in": allowed_vis}}
    if audio_id:
        where = {"$and": [{"visibility": {"$in": allowed_vis}}, {"audio_id": audio_id}]}
    fetch_k = min(max(k * 5, k), 50)
    return vs.similarity_search_with_score(query, k=fetch_k, filter=where)


def _build_audio_hits(docs_scores, allowed_vis_set: set[str], base: str, mode: str = "hit"):
    """把向量搜索结果docs_scores转换成业务层能用的结构AudioSearchHit或AudioCitation
    _build_audio_hits 执行流程
      │
      ├─ 遍历向量检索结果（doc + score）
      ├─ 从 metadata 提取 audio_id / segment_id / start_ms / end_ms
      ├─ 丢弃非法或脏数据（缺字段 / 时间区间非法）
      ├─ 构造业务唯一键（audio + segment + time）
      ├─ 去重（seen 集合）
      ├─ 查询 audio_document（事实源校验）
      ├─ 权限兜底过滤（visibility）
      ├─ 读取正文文本（page_content）
      ├─ 生成 clip_url
      ├─ 按 mode 封装 DTO
      │     ├─ hit → AudioSearchHit
      │     └─ citation → AudioCitation
      └─ 返回最终 hits / citations 列表

    #把「向量检索结果（LangChain doc + score）」
    👉 过滤 + 去重 + 权限校验
    👉 转成「业务层可直接返回的 AudioSearchHit / AudioCitation」
    hits 是「音频向量检索后的 最终可返回结果列表」——已经 去重 + 权限校验 + 业务封装 过的音频片段集合。
    seen用于防止重复片段，比如多个检索结果指向相同音频区间
    初始化：结果集 + 去重容器⚠️ 向量检索非常容易出现同一片段被多次命中所以要用seen
    """
    results, seen = [], set()
    for doc, score in docs_scores:#遍历每个向量结果
        md = doc.metadata or {}#从 metadata 里抽“业务必需字段”
        audio_id = str(md.get("audio_id") or "").strip()
        segment_id = str(md.get("segment_id") or "").strip()
        if not (audio_id and segment_id):#如果缺字段，直接丢弃：👉 这是容错 + 防脏数据
            continue
        try:
            start_ms, end_ms = int(md.get("start_ms", 0)), int(md.get("end_ms", 0)) #校验时间区间合法性  这是非常重要的一层 安全网：
                                                                                    # 防止 ES / 向量库脏数据
                                                                                    # 防止 clip 接口被打爆
        except Exception:
            continue
        if start_ms < 0 or end_ms <= start_ms:
            continue



        key = (audio_id, segment_id, start_ms, end_ms)#构造“业务级唯一键   ”去重“音频 + 段 + 时间区间” = 真实世界唯一片段
        if key in seen:
            continue
        seen.add(key)  # 生成唯一key，即同一个片段唯一标识，所以这里用了set集合
        db_doc = audio_db.get_audio_document(audio_id)#查询 audio_document（上层事实源）
        if not db_doc:
            continue
        if (db_doc.get("visibility") or "").strip().lower() not in allowed_vis_set:#权限过滤（最终兜底）
            continue
        text = (doc.page_content or "").strip()#todo 拿正文文本
        # 根据 mode 构造不同 DTO（数据传输对象）
        # 搜索模式（query / search）
        if mode == "hit":  # hit搜索结果列表/query，返回AudioSearchHit
            results.append(AudioSearchHit(#问答引用（ask / stream）
                audio_id=audio_id, segment_id=segment_id,
                start_ms=start_ms, end_ms=end_ms, text=text,
                score=float(score) if score is not None else None,
                clip_url=_clip_url(base, audio_id, start_ms, end_ms)#clip_url 在这里统一生成（👍）
            ))
        else: # citation问答引用/ask/stream接口，结果是AudioCitation
            results.append(AudioCitation(#问答引用（ask / stream）
                audio_id=audio_id, segment_id=segment_id,
                start_ms=start_ms, end_ms=end_ms, text=text,
                clip_url=_clip_url(base, audio_id, start_ms, end_ms),#clip_url 在这里统一生成（👍）
                score=float(score) if score is not None else None
            ))
    return results

# =========================
# V1: ingest/job/doc/query/ask/clip
# =========================



#todo 上传音频 (/audio/ingest)
@router.post("/ingest", response_model=AudioIngestAsyncResp)
async def ingest_audio(
    file: UploadFile = File(...),
    visibility: str = Form("public"),
    audio_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    delete_old_file: bool = Form(False),
    current_user: UserInDB = Depends(get_current_user),):

    """
    HTTP 请求
      │
      ├─ 权限校验（kb.manage_docs）
      ├─ 参数校验（filename / visibility / overwrite）
      ├─ 冲突校验（audio_id 是否运行 / 是否已存在）
      ├─ 原始文件落盘（AUDIO_DIR）
      ├─ 写 audio_documents（status=queued）
      ├─ 创建 audio_jobs（job_id）
      ├─ 投递 Celery ingest task
      └─ 返回 job_id / audio_id / status_url
    """

    _require_manage_docs(current_user)

    if not file.filename:#基本参数校验，防止空上传
        raise HTTPException(status_code=400, detail="Empty filename")
    #标准化 / 生成 ID
    visibility = _normalize_visibility(visibility or "public")
    audio_id = (audio_id or f"aud-{uuid.uuid4().hex[:12]}").strip()#audio_id：业务资源 ID
    job_id = f"job-{uuid.uuid4().hex[:12]}"#job_id：处理流程 ID

    if audio_db.is_audio_running(audio_id):#防止同一音频并发处理🚫 这是你避免状态炸裂的第一道防线
        raise HTTPException(status_code=409, detail="audio is running, try later")

    existed = audio_db.get_audio_document(audio_id)
    if existed and not overwrite:#默认不允许覆盖  overwrite=true → 允许，但：记录 old_stored_path交给 job 决定是否删除
        raise HTTPException(status_code=409, detail="audio_id already exists; set overwrite=true")

    old_stored_path = existed["stored_path"] if existed else None

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename).suffix or ".bin"
    raw_path = AUDIO_DIR / f"{int(time.time())}_{uuid.uuid4().hex}{suffix}"
    raw_bytes = await file.read()            #保存原始文件
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    raw_path.write_bytes(raw_bytes)

    audio_db.upsert_audio_document(                                 #👉 这是“事实源”，worker 以后只更新它
        audio_id=audio_id,
        original_filename=file.filename,
        stored_path=str(raw_path),
        duration_ms=0,
        language=language,
        visibility=visibility,
        status="queued",
        uploader_user_id=int(getattr(current_user, "id", 0) or 0) or None,
        uploader_username=getattr(current_user, "username", None),
        segment_count=0,
    )

    audio_job_db.create_job(# 创建 audio_job
        job_id,
        audio_id,
        overwrite=bool(overwrite),
        delete_old_file=bool(delete_old_file),
        old_stored_path=old_stored_path if overwrite else None,
    )

    async_result = audio_ingest_task.apply_async(# Celery 投递   不关心执行结果只拿 task_id
        args=[job_id, audio_id],
        queue=getattr(settings, "celery_audio_queue", "audio"),
    )
    audio_job_db.bind_task(job_id, async_result.id)# 绑定 task_id

    return AudioIngestAsyncResp(
        job_id=job_id,
        audio_id=audio_id,
        stored_as=str(raw_path),
        visibility=visibility,
        celery_task_id=async_result.id,
        status_url=f"/audio/jobs/{job_id}",
    )


#todo 音频作业管理 (/audio/jobs/...)
@router.get("/jobs/{job_id}", response_model=AudioJobResp)

def get_audio_job(
    job_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
        GET /audio/jobs/{job_id} = 查询单个音频作业状态的管理接口
        👉 只给 kb.manage_docs
        👉 用来看 job 在干什么 / 干到哪 / 有没有报错
        👉 不是给普通用户或前端播放器用的
    """
    _require_manage_docs(current_user)
    row = audio_job_db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return row


#todo音频处理任务的“管理态取消接口”
@router.post("/jobs/{job_id}/cancel")

def cancel_audio_job(
    job_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
        POST /jobs/{job_id}/cancel = 音频处理任务的“管理态取消接口”
        👉 只能管理员用
        👉 只是发出取消请求，不是强杀
        👉 是否真正停止，取决于 worker 是否配合
    """
    _require_manage_docs(current_user)
    ok = audio_job_db.request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, "cancel_requested": True}

#todo 管理态接口（admin / ops）
@router.get("/docs/{audio_id}", response_model=AudioDocDetail)

def get_audio_doc(
    audio_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """
        GET /docs/{audio_id} = 管理态接口（admin / ops）
        👉 只给「能管理文档的人」看
        👉 返回的是 音频文档本体（metadata）
        👉 不是给搜索 / 播放用的
    """
    _require_manage_docs(current_user)
    row = audio_db.get_audio_document(audio_id)
    #查数据库不是向量库是你真实的 audio_documents 表 包含：stored_path,visibility,duration,created_at处理状态等
    if not row:
        raise HTTPException(status_code=404, detail="audio not found")
    return row




# todo 音频查询 (/audio/query)
@router.get("/query", response_model=AudioSearchResp)

def query_audio(
        request: Request,
        q: str = Query(..., min_length=1),#拿到用户输入的搜索词 q，
        k: int = Query(6, ge=1, le=20),#控制返回数量 k
        current_user: UserInDB = Depends(get_current_user),#已认证的 current_user
) -> AudioSearchResp:
    """
        HTTP 请求
          │
          ├─ 权限计算（allowed_visibilities）
          ├─ 向量检索（audio segments）
          ├─ 去重 + 权限兜底
          ├─ 构造 hits（clip_url）
          └─ 返回搜索结果列表

        query_audio = 纯检索接口 👉 只做「向量搜索 + 权限过滤 + 命中片段返回」
    """
    allowed_vis = _get_allowed_and_check(current_user)
    allowed_vis_set = set(allowed_vis)
    vs = get_audio_vs()                                                     # 拿向量库实例ES / Chroma / Milvus / FAISS 的封装后面所有检索都走它
    base = _absolute_base(request)                                          # 构造 base URL（给 clip 用）

    docs_scores = _search_audio_segments(vs, q, allowed_vis, k)             # 向量搜索音频片段这是整条链路的“心脏”：
                                                                            # 输入：
                                                                            # 查询文本 q
                                                                            # 可见性 allowed_vis
                                                                            # 返回数量 k
                                                                            # 输出：
                                                                            # (Document, score)[]
                                                                            # 每个 Document ≈ 一个 音频 segment
    hits = _build_audio_hits(docs_scores, allowed_vis_set, base, mode="hit")# 命中构建（去重 + DB 校验 + URL）

    return AudioSearchResp(q=q, k=k, allowed_visibilities=allowed_vis, hits=hits)

#todo /search 只是 /query 的一个对外“马甲接口”所有真实逻辑都在 query_audio。
@router.get("/search", response_model=AudioSearchResp)

def search_audio(*args, **kwargs):
    return query_audio(*args, **kwargs)

@router.post("/ask", response_model=AudioAskResp)
        # /ask 做的事是：
        # 去音频库里 找最相关的片段
        # 把这些片段的文字内容拼成“参考材料”
        # 让大模型 基于这些材料回答
        # 顺便告诉前端：
        # 这些答案是基于哪几段音频
        # 每一段音频在哪个时间区间
        # 给你一个 clip_url，你要听可以点
def ask_audio(req: AudioAskReq, request: Request, current_user: UserInDB = Depends(get_current_user)) -> AudioAskResp:
    """
        HTTP 请求
          │
          ├─ 权限计算（allowed_visibilities）
          ├─ 向量检索（audio segments）
          ├─ 去重 + 权限兜底
          ├─ 构造 citations（clip_url）
          ├─ 构造 RAG messages
          ├─ 调用 LLM（可选）
          └─ 返回 answer + citations
      """
    # ask_audio =在用户权限范围内 → 用问题做向量检索 → 找出最相关的音频片段 →
    # 生成可引用的 citations → 用这些文本让 LLM 回答 → 返回 JSON
    question = (req.question or "").strip()#拿到用户的问题 规范化用户输入
    k = max(1, min(int(req.k or 6), 20))# 控制最多返回多少个音频片段（citations）

    allowed_vis = _compute_allowed_visibilities(current_user)#“用户能看的音频范围”（权限）public：所有人 internal：只有有权限的人
    allowed_vis_set = set(allowed_vis)

    vs = get_audio_vs()#准备检索环境vs：音频文本的向量索引（ask 的“知识库”）base：构造 clip_url 用（ask 不生成音频，只给链接
    base = _absolute_base(request)

    where: dict[str, Any] = {"visibility": {"$in": allowed_vis}}#构造向量检索条件默认：在「你能看的所有音频」里搜指定 audio_id：只在某一条音频里问
    if req.audio_id:
        where = {"$and": [{"visibility": {"$in": allowed_vis}}, {"audio_id": req.audio_id}]}

    fetch_k = min(max(k * 5, k), 50)


    try:
        docs_scores = vs.similarity_search_with_score(question, k=fetch_k, filter=where)# 向量检索（核心之一）把 question → embedding
                                                                                        # 去音频切分后的文本 segment 里找最像的
                                                                                        # 返回：
                                                                                        # 文本内容
                                                                                        # metadata（audio_id / segment_id / start_ms / end_ms）
                                                                                        # 相似度 score
    except TypeError:
        docs_scores = vs.similarity_search_with_score(question, k=fetch_k, where=where)

    citations: list[AudioCitation] = []
    seen: set[tuple[str, str, int, int]] = set()#去重 + 合法性校验（防脏数据）
                                                #去重（同一段不重复引用）
                                                #校验时间范围
                                                #防 metadata 异常

    for doc, score in docs_scores:
        md = doc.metadata or {}
        audio_id = str(md.get("audio_id") or "").strip()
        segment_id = str(md.get("segment_id") or "").strip()
        if not audio_id or not segment_id:
            continue

        try:
            start_ms = int(md.get("start_ms") or 0)
            end_ms = int(md.get("end_ms") or 0)
        except Exception:
            continue
        if start_ms < 0 or end_ms <= start_ms:
            continue

        key = (audio_id, segment_id, start_ms, end_ms)
        if key in seen:
            continue
        seen.add(key)

        db_doc = audio_db.get_audio_document(audio_id)# 再次查 DB + 再次做权限兜底（非常关键）
        #这一段非常重要：即使向量库里有脏数据，ask 也不会越权这是你整个系统里权限最稳的一层。
        if not db_doc:
            continue
        doc_vis = (db_doc.get("visibility") or "").strip().lower()
        if doc_vis not in allowed_vis_set:
            continue

        text = (doc.page_content or "").strip()
        citations.append(                                                       # 构造 citation（ask 的第二个核心）ask 不返回音频，只返回“证据链”
            AudioCitation(  # 每个 citation 都是：
                            # LLM 用来回答的证据
                            # 前端用来播放的入口
                audio_id=audio_id,
                segment_id=segment_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                clip_url=_clip_url(base, audio_id, start_ms, end_ms),
                score=float(score) if score is not None else None,
            )
        )
        if len(citations) >= k:#保证输出规模稳定，防止 prompt 爆炸
            break

    if not citations:#没命中 → 直接返回（不调用 LLM）
        return AudioAskResp(question=question, answer="没有检索到相关音频片段。", citations=[])

    api_key = getattr(settings, "openai_api_key", "") or ""
    model = getattr(settings, "model_name", "") or "gpt-4o-mini"

    if not api_key:#决定是否调用大模型
        return AudioAskResp(
            question=question,
            answer="(未配置 OPENAI_API_KEY) 已返回相关音频片段引用，可先基于citations手动判断。",
            citations=citations,
        )

    messages = _build_rag_messages(question, citations, req.system_prompt)#构造 RAG Prompt
    answer = _openai_chat_complete(model=model, api_key=api_key, messages=messages, timeout_s=90.0)#调用 LLM 生成答案

    return AudioAskResp(question=question, answer=answer, citations=citations)#返回最终结果（JSON）

#todo 音频切片 (/audio/docs/{audio_id}/clip)从一个音频里，按时间范围或按 segment，裁剪一小段 mp3，返回给客户端，并在返回后自动删除临时文件。这是一个 “即时生成 + 临时文件 + 流式返回” 的接口
@router.get("/docs/{audio_id}/clip")
# 从一个音频里，按时间范围或按 segment，裁剪一小段 mp3，返回给客户端，并在返回后自动删除临时文件。这是一个 “即时生成 + 临时文件 + 流式返回” 的接口
# 这是一个：
# - 即时生成（ffmpeg 同步）
# - 临时文件（mp3 落盘）
# - FileResponse 流式返回
# - 试图在响应后删除临时文件
#
# ⚠️ 关键风险点：
# FileResponse 是“服务端流式”，BackgroundTasks 只保证 response 完成，
# 不保证客户端“播放 / seek / Range 请求”完成。


def get_audio_clip(
    audio_id: str,
    background_tasks: BackgroundTasks,
    start_ms: Optional[int] = Query(default=None, ge=0),
    end_ms: Optional[int] = Query(default=None, ge=0),
    segment_id: Optional[str] = Query(default=None),  # e.g. aud-xxx:3
    current_user: UserInDB = Depends(get_current_user),
):
    """
        HTTP 请求
          │
          ├─ 权限校验（audio visibility）
          ├─ 解析 segment_id / time range
          ├─ 校验时间区间合法性
          ├─ ffmpeg 裁剪生成 mp3
          ├─ FileResponse 流式返回
          └─ 响应结束后删除临时文件（⚠️ 有 Range 风险）
    """
    doc = audio_db.get_audio_document(audio_id)
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    _ensure_can_access_visibility(current_user, doc.get("visibility") or "")

    if segment_id:
        #情况一：用 segment_id
        # 执行顺序（真实）：
        # 1. 根据 segment_id 查 segment（start_ms / end_ms）
        # 2. ffmpeg 同步生成 mp3 → 写入 data/audio_clips/xxx.mp3
        # 3. return FileResponse(...)
        # 4. ASGI 打开 mp3 文件
        # 5. ASGI 以 chunk 方式流式发送给客户端
        # 6. 文件发送完毕，response 被标记为 completed
        # 7. BackgroundTasks 开始执行
        # 8. unlink(mp3) → 临时文件被删除 ❌
        #
        # 后果：
        # - 单次下载“看起来正常”
        # - 任何后续 Range / seek / 重拉都会失败

        if ":" not in segment_id:
            raise HTTPException(status_code=400, detail="invalid segment_id format")
        seg_audio_id, seg_idx_str = segment_id.split(":", 1)
        if seg_audio_id != audio_id:
            raise HTTPException(status_code=400, detail="segment_id does not match audio_id")
        try:
            seg_idx = int(seg_idx_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid segment_idx in segment_id")

        seg = audio_db.get_audio_segment(audio_id, seg_idx)
        if not seg:
            raise HTTPException(status_code=404, detail="segment not found")

        start_ms = int(seg["start_ms"])
        end_ms = int(seg["end_ms"])
    else:
        #情况二：用 start_ms / end_ms
        # 执行顺序：
        # 1. 校验 start_ms / end_ms
        # 2. ffmpeg 同步生成 mp3
        # 3. return FileResponse
        # 4. ASGI 流式发送文件
        # 5. response 完成
        # 6. BackgroundTasks 删除文件 ❌
        #
        # 与情况一的区别：
        # - 仅参数来源不同
        # - 文件生命周期、问题完全一致

        if start_ms is None or end_ms is None:
            raise HTTPException(status_code=400, detail="start_ms and end_ms are required")

    if end_ms <= start_ms:
        raise HTTPException(status_code=400, detail="end_ms must be greater than start_ms")

    max_clip_ms = 5 * 60 * 1000
    if (end_ms - start_ms) > max_clip_ms:
        raise HTTPException(status_code=400, detail="clip too long")

    src_path = Path(doc["stored_path"])


    if not src_path.exists():
        raise HTTPException(status_code=404, detail="stored audio file missing")

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    clip_name = f"{audio_id}_{start_ms}_{end_ms}_{uuid.uuid4().hex[:8]}.mp3"
    clip_path = CLIP_DIR / clip_name

    try:
        clip_audio_to_mp3(src_path=src_path, dst_path=clip_path, start_ms=int(start_ms), end_ms=int(end_ms))
    except Exception:
        raise HTTPException(status_code=500, detail="failed to generate clip")

    background_tasks.add_task(lambda p=str(clip_path): Path(p).unlink(missing_ok=True))     # FastAPI 的 BackgroundTasks 行为是：响应返回给客户端之后，立即执行后台任务
                                                                                            # 1. ffmpeg 切出 mp3 → 写入 data/audio_clips/xxx.mp3
                                                                                            # 2. FileResponse 把文件流式返回给客户端
                                                                                            # 3. 响应完成
                                                                                            # 4. 后台任务执行 → unlink() → 文件被删除 ❌

    return FileResponse(path=str(clip_path), media_type="audio/mpeg", filename=clip_name)





# =========================
# [ADD] V2-2: segments list
# =========================
#todo “在确认你有权限的前提下，返回某个音频被切成的所有时间段（segments）列表。”
@router.get("/docs/{audio_id}/segments")
def list_audio_segments_api(audio_id: str, current_user: UserInDB = Depends(get_current_user)):
    doc = audio_db.get_audio_document(audio_id)#确认音频存在
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    _ensure_can_access_visibility(current_user, doc.get("visibility") or "")#可见性查询
    segs = audio_db.list_audio_segments(audio_id)#查询 segments 列表
    return {
        "audio_id": audio_id,
        "visibility": (doc.get("visibility") or "public"),
        "segment_count": len(segs),
        "segments": segs,
    }

# =========================
# [ADD] V2-3: transcript
# =========================
#todo “在确认你有权限的前提下，返回某个音频的完整转写文本（transcript）。”
@router.get("/docs/{audio_id}/transcript")
def get_audio_transcript_api(audio_id: str, current_user: UserInDB = Depends(get_current_user)):
    doc = audio_db.get_audio_document(audio_id)#查音频是否存在（存在性校验）
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    _ensure_can_access_visibility(current_user, doc.get("visibility") or "")#可见性查询
    out = audio_db.get_audio_transcript(audio_id)#真正的数据读取（核心逻辑）此时才：查 transcript 表 / JSON,不再担心越权
    out["visibility"] = (doc.get("visibility") or "public")
    return out

# =========================
# [ADD] V2-4: DELETE doc (db + vectors + files)
# =========================
#todo 彻底删除一个音频文档（Hard Delete）
@router.delete("/docs/{audio_id}")


def delete_audio_doc_api(audio_id: str, current_user: UserInDB = Depends(get_current_user)):
    """
    彻底删除一个音频文档（Hard Delete）
    DELETE audio
    │
    ├─ 权限校验
    ├─ 校验 audio 是否存在
    │
    ├─ 1) 删除向量（ES / VectorStore）
    ├─ 2) 删除数据库记录（级联）
    ├─ 3) 删除文件
    │   ├─ 原始音频
    │   ├─ wav 中间文件
    │   └─ clip 临时文件
    │
    └─ 返回删除结果汇总
    在执行函数之前，先调用 get_current_user()，把返回值作为 current_user 传进来
    UserInDB = “从数据库里读出来的、可信的用户对象”
    Depends = 把“前置逻辑”交给 FastAPI 自动执行，并把结果注入进来.
    它做三件事
    1.调用一个函数
    2.拿到返回值
    3.作为参数传给你的接口函数
    """

    _require_manage_docs(current_user)

    doc = audio_db.get_audio_document(audio_id)                       #如果数据库里根本没有这个 audio，就直接返回 404，后面的逻辑全部不应该再执行
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    # 1) delete vectors
    vec_deleted = 0                                                   #先初始化为 0
    try:
        vec_deleted = int(delete_by_audio_id(audio_id) or 0)          #尝试删除向量
    except Exception:
        vec_deleted = 0

    # 2) delete db rows
    db_deleted = audio_db.delete_audio_document_cascade(audio_id)     #在数据库中，按 audio_id 执行一次「级联删除」级联删除：删除“这个 audio 相关的所有数据库数据”

    # 3) delete files
    files_deleted: list[str] = []                                     #记录“成功删除了哪些文件”
    errors: list[str] = []                                            #记录“删除过程中发生了哪些非致命错误”

    # raw audio
    # 从 DB 里取 stored_path
    # 构造文件路径
    # 存在且是文件才删
    # 成功 → 记入 files_deleted
    # 失败 → 记入 errors
    try:
        p = Path(doc.get("stored_path") or "")
        if p.exists() and p.is_file():
            p.unlink()
            files_deleted.append(str(p))
    except Exception as e:
        errors.append(f"delete raw failed: {e}")

    # wav
    # 拼出 wav 文件路径
    # 判断文件是否存在、是否是普通文件
    # 删除文件
    # 记录成功删除的文件
    # 捕获并记录异常
    try:
        wav = WAV_DIR / f"{audio_id}.wav"
        if wav.exists() and wav.is_file():
            wav.unlink()
            files_deleted.append(str(wav))
    except Exception as e:
        errors.append(f"delete wav failed: {e}")

    # clips: normally temp-delete, but if crashed, may remain; best-effort cleanup prefix
    # 判断 clips 目录是否存在
    # 找出所有 audio_id_*.mp3 的文件
    # 逐个尝试删除
    # 成功的记录
    # 单个失败直接忽略
    # 整体异常才记录 error
    try:
        if CLIP_DIR.exists():
            for fp in CLIP_DIR.glob(f"{audio_id}_*.mp3"):
                try:
                    fp.unlink()
                    files_deleted.append(str(fp))
                except Exception:
                    pass
    except Exception as e:
        errors.append(f"delete clips failed: {e}")
    # 它回答的不是：
    # “删成功了吗？”
    # 而是：
    # “我刚刚试图删什么？删到了什么程度？哪里可能有问题？”
    return {
        "audio_id": audio_id,
        "vectors_deleted": vec_deleted,
        "db_deleted": db_deleted,
        "files_deleted": files_deleted,
        "errors": errors,
    }

# =========================
# [ADD] V2-5: reindex (async job)
# =========================

@router.post("/docs/{audio_id}/reindex")
#这是一个“触发音频重建索引的后台任务”的 API——校验权限 → 校验状态 → 创建 Job → 派发 Celery Task → 返回任务信息
def reindex_audio_doc_api(audio_id: str, current_user: UserInDB = Depends(get_current_user)):               # current_user当前登录用户（FastAPI 依赖注入）
    _require_manage_docs(current_user)

    if audio_db.is_audio_running(audio_id):                                                                 # 检查这个 audio 是否已经被某个任务占用
        raise HTTPException(status_code=409, detail="audio is running, try later")

    doc = audio_db.get_audio_document(audio_id)                                                             # 如果数据库里根本没有这个 audio，就直接返回 404，后面的逻辑全部不应该再执行
    if not doc:
        raise HTTPException(status_code=404, detail="audio not found")

    # 在数据库里创建一个“业务 Job（作业）记录”，用来追踪一次音频重建索引的全过程
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    audio_job_db.create_job(job_id, audio_id, overwrite=False, delete_old_file=False, old_stored_path=None)# 这一步 不是“执行任务”，而是：在数据库里登记：我要开始做一件事了

    async_result = audio_reindex_task.apply_async(                                                         # 把“业务 job”交给 Celery，生成一个真正会跑的 task
        args=[job_id, audio_id],
        queue=getattr(settings, "celery_audio_queue", "audio"),
    )
    audio_job_db.bind_task(job_id, async_result.id)                                                        # 把 task_id 回写到 job 里，完成“绑定”
                                                                                                           # job 是“合同”，task 是“施工队”bind_task 是“合同上写明施工队编
    return {                                                                                               # 这是后端对前端的正式承诺：“这个音频的 reindex 已经受理了，你可以用这些信息持续跟踪它。”
        "job_id": job_id,#前端 / API 使用的主 ID
        "audio_id": audio_id,#说明这个 job 是针对哪个音频
        "celery_task_id": async_result.id,#Celery 内部的执行 ID
        "status_url": f"/audio/jobs/{job_id}",#它定义了：前端接下来该怎么“继续这个故事，定义下一个接口的调用”
    }

# =========================
# [ADD] V2-1: SSE /audio/ask/stream
# =========================
# 先检索出“允许当前用户看的音频片段（citations）” →
# 再把问题 + citations 丢给 DeepSeek →
# 把模型一边生成的内容，一边通过 SSE 实时推给前端


#todo _sse 把一个 Python 对象，包装成符合 SSE 协议规范的“事件帧”，再编码成字节，交给 StreamingResponse 发给客户端。
def _sse(event: str, data: Any) -> bytes:

    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")




@router.post("/ask/stream")

# 这段代码的作用是：
# 在真正调用 DeepSeek 之前，
# 把“能用于回答问题的音频片段（citations）”安全、准确地找出来。

# def ask_audio_stream(req: AudioAskReq, request: Request, current_user: UserInDB = Depends(get_current_user)):
#     question = (req.question or "").strip()
#     k = max(1, min(int(req.k or 6), 20))
#     if not question:
#         raise HTTPException(status_code=400, detail="question is empty")
#
#     allowed_vis = _compute_allowed_visibilities(current_user)
#     allowed_vis_set = set(allowed_vis)
#
#     vs = get_audio_vs()
#     base = _absolute_base(request)
#
#     where: dict[str, Any] = {"visibility": {"$in": allowed_vis}}
#     if req.audio_id:
#         where = {"$and": [{"visibility": {"$in": allowed_vis}}, {"audio_id": req.audio_id}]}
#
#     fetch_k = min(max(k * 5, k), 50)
#     try:
#         docs_scores = vs.similarity_search_with_score(question, k=fetch_k, filter=where)
#     except TypeError:
#         docs_scores = vs.similarity_search_with_score(question, k=fetch_k, where=where)
#
#     citations: list[AudioCitation] = []
#     seen: set[tuple[str, str, int, int]] = set()
#     for doc, score in docs_scores:
#         md = doc.metadata or {}
#         audio_id = str(md.get("audio_id") or "").strip()
#         segment_id = str(md.get("segment_id") or "").strip()
#         if not audio_id or not segment_id:
#             continue
#
#         try:
#             start_ms = int(md.get("start_ms") or 0)
#             end_ms = int(md.get("end_ms") or 0)
#         except Exception:
#             continue
#         if start_ms < 0 or end_ms <= start_ms:
#             continue
#
#         key = (audio_id, segment_id, start_ms, end_ms)
#         if key in seen:
#             continue
#         seen.add(key)
#
#         db_doc = audio_db.get_audio_document(audio_id)
#         if not db_doc:
#             continue
#         doc_vis = (db_doc.get("visibility") or "").strip().lower()
#         if doc_vis not in allowed_vis_set:
#             continue
#
#         text = (doc.page_content or "").strip()
#         citations.append(
#             AudioCitation(
#                 audio_id=audio_id,
#                 segment_id=segment_id,
#                 start_ms=start_ms,
#                 end_ms=end_ms,
#                 text=text,
#                 clip_url=_clip_url(base, audio_id, start_ms, end_ms),
#                 score=float(score) if score is not None else None,
#             )
#         )
#         if len(citations) >= k:
#             break
#
#     api_key = os.getenv("DEEPSEEK_API_KEY", "")
#     model = "deepseek-reasoner"
#
#
#
#     # gen() 是一个「SSE 事件生成器」：
#     # 它把一次 RAG + LLM 推理过程，拆成一连串事件，
#     # 按顺序、实时地 yield 给前端。
#
#     def gen():
#         # meta first
#         yield _sse(
#             "meta",
#             {
#                 "question": question,
#                 "allowed_visibilities": allowed_vis,
#                 "citations": [c.model_dump() for c in citations],
#             },
#         )
#
#         if not citations:
#             yield _sse("token", {"text": "没有检索到相关音频片段。"})
#             yield _sse("done", {"ok": True})
#             return
#
#         if not api_key:
#             yield _sse(
#                 "token",
#                 {"text": "(未配置 DEEPSEEK_API_KEY) 只能返回 citations，无法流式生成答案。"},
#             )
#             yield _sse("done", {"ok": True})
#             return
#
#         messages = _build_rag_messages(question, citations, req.system_prompt)
#
#         try:
#             for kind, text in _deepseek_reasoner_stream(
#                 api_key=api_key,
#                 model="deepseek-reasoner",
#                 messages=messages,
#             ):
#                 if kind == "reasoning":
#                     yield _sse("reasoning", {"text": text})
#                 else:
#                     yield _sse("token", {"text": text})
#
#         except Exception as e:
#             yield _sse("error", {"detail": str(e)})
#         finally:
#             yield _sse("done", {"ok": True})
#
#     return StreamingResponse(
#         gen(),
#         media_type="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "X-Accel-Buffering": "no",  # nginx 必须
#         },
#     )
#
# # 这是个把 DeepSeek 的“流式生成结果”转换成你自己系统可用格式的「适配器函数」。这个函数的作用是：
# # 调用 DeepSeek 的“流式聊天接口”，
# # 把模型一边生成的文本，一边拆成小片段（token），
# # 然后 yield 给你的 SSE 接口实时发给前端。
#
# def _deepseek_reasoner_stream(
#     *,
#     api_key: str,
#     model: str,
#     messages: list[dict],
# ) -> Iterator[tuple[str, str]]:
#     client = OpenAI(
#         api_key=api_key,
#         base_url="https://api.deepseek.com",
#     )
#
#     stream = client.chat.completions.create(
#         model=model,
#         messages=messages,
#         stream=True,
#     )
#
#     for chunk in stream:
#         if not chunk.choices:
#             continue
#
#         delta = chunk.choices[0].delta
#
#         # DeepSeek 暂时不区分 reasoning / token
#         if delta.content:
#             yield ("token", delta.content)
@router.post("/ask/stream")
#todo 权限 → 检索 → 证据 → Prompt → 推理 → Streaming → 前端

def ask_audio_stream(
    req: dict,
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
):
    """
    这段代码的作用本质上就是在“区分 / 校验请求体是不是一个合法的 JSON 对象（dict）”，
    但要说清楚一点，它不是在区分“是不是 JSON 文件”，而是在区分：👉 请求体解析出来之后，是不是一个 JSON object（dict）
    """
    question = (req.get("question") or "").strip()
    audio_id = req.get("audio_id")
    k = max(1, min(int(req.get("k") or 6), 20))

    if not question:
        raise HTTPException(status_code=400, detail="question is empty")

    allowed_vis = _get_allowed_and_check(current_user)
    allowed_vis_set = set(allowed_vis)
    vs = get_audio_vs()
    base = _absolute_base(request)

    docs_scores = _search_audio_segments(vs, question, allowed_vis, k, audio_id)
    citations = _build_audio_hits(docs_scores, allowed_vis_set, base, mode="citation")

    messages = _build_rag_messages(question, citations, None)

    def event_stream():
        """
        这是一个 SSE（Server-Sent Events）事件生成器
        把一次「RAG + LLM 流式生成」拆成三类事件，边算边推给前端：
        meta：一次性发元信息（问题 + 引用片段）
        token：模型生成的每一小段文本
        done：告诉前端“生成结束了
        """
        yield f"event: meta\ndata: { {'question': question, 'citations': [c.model_dump() for c in citations]} }\n\n"
        for chunk in _openai_stream(messages=messages):
            yield f"event: token\ndata: {chunk}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/admin/reset_es_audio_index")

def admin_reset_es_audio_index(current_user: UserInDB = Depends(get_current_user)):
    """删掉并重建 ES 的音频索引"""
    # 这里沿用你已有的 kb.manage_docs 管理权限逻辑
    perms = set(getattr(current_user, "permissions", []) or [])
    if not getattr(current_user, "is_super_admin", False) and "kb.manage_docs" not in perms:
        raise HTTPException(status_code=403, detail="Missing permission: kb.manage_docs")

    reset_audio_index()
    return {"ok": True, "index": settings.es_audio_index}




