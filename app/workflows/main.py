import time
import uuid
from typing import Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from app.db import kb_db
from app.db.redis_session import load_session, save_session
from app.ingestion.loader import load_docs, split_docs
from app.model.auth_model import UserInDB
from app.service.visibility_service import normalize_visibility
from app.web.auth_api import auth_router, get_current_user
from app.workflows.config import settings
import chromadb
from app.ingestion.loader import load_single_file, split_with_visibility
from app.workflows.deps import get_vs
from app.workflows.router_graph import router_graph
from app.service.rbac_service import check_permission
from app.web.rbac_api import rbac_router
from fastapi import Depends
from app.web.kb_api import router as kb_router
from app.rag.chroma_admin_kb import count_by_doc_id
from app.web.audio_api import router as audio_router
from app.web.audio_admin_api import router as audio_admin_router

app = FastAPI(title="Enterprise KB Assistant")
app.include_router(auth_router)
app.include_router(kb_router)
app.include_router(audio_router)
app.include_router(rbac_router)
app.include_router(audio_admin_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 本地开发可以先全开，线上再收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
DATA_DOCS_DIR = Path("../../data/docs")
DATA_DOCS_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS: dict[str, dict] = {}


class ChatReq(BaseModel):
    text: str
    user_role: str = "public"
    requester: str = "anonymous"
    mode:Optional[str] =None
    session_id:Optional[str] = None
class ChatResp(BaseModel):
    answer: str
    session_id: Optional[str] = None  # ⚠️添加
    active_route: Optional[str] = None # ⚠️添加

@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq,
         current_user=Depends(get_current_user)):
    # 允许访问公共知识库
    check_permission(current_user, "kb.view_public")
    payload = req.model_dump()
    text = payload.get("text") or payload.get("question") or ""

    # 1) get or create session id
    sid = payload.get("session_id") or f"sid-{uuid.uuid4().hex[:10]}"
    payload["session_id"] = sid

    # 2) load previous state from redis and merge
    prev_state = load_session(sid)
    if prev_state:
        merged = {**prev_state, **payload}
        merged["text"] = text
        payload = merged

    # 3) run router graph
    out = router_graph.invoke(payload)

    # 4) save new state to redis
    new_state = {**payload, **out}
    save_session(sid, new_state)

    return {
        "answer": out.get("answer"),
        "session_id": sid,
        "active_route": new_state.get("active_route"),
    }

@app.post("/ingest")
async def ingest(file:UploadFile = File(...),
                 visibility: str = Form("public"),
                 doc_id:Optional[ str] = Form(None),
                 overwrite: bool = Form(False),
                 delete_old_file: bool = Form(False),
                 current_user:UserInDB=Depends(get_current_user),):
    """
        文档入库：需要 kb.manage_docs 权限
        """
    check_permission(current_user, "kb.manage_docs")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")
    visibility = normalize_visibility(visibility or "public")
    doc_id = (doc_id or f"doc-{uuid.uuid4().hex[:12]}").strip()
    existed = kb_db.get_kb_document(doc_id)
    if existed and not overwrite:
        raise HTTPException(status_code=409, detail=f"doc_id already exists: {doc_id}")
    if existed and overwrite:
        old_path = existed["stored_path"] if existed else None
        # old_path里面放的是旧文档存放的路径

        # 1) 先把新文件保存下来
        suffix = Path(file.filename).suffix
        safe_name = f"{int(time.time())}_{uuid.uuid4().hex}{suffix}"
        save_path = DATA_DOCS_DIR / safe_name

        content = await file.read()  # 因为上传文件时间较长


    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    save_path.write_bytes(content)

    # 2) 先解析新文件、切分出 chunks（确保新文件 OK）
    docs = load_single_file(save_path)
    if not docs:
        raise HTTPException(status_code=400, detail=f"Unsupported or empty file type: {suffix}")

    extra_meta = {
        "original_filename": file.filename,
        "stored_path": str(save_path),
        "uploader_user_id": current_user.id,
        "uploader_username": current_user.username,
        "uploaded_at": int(time.time()),
    }
    chunks = split_with_visibility(docs, visibility=visibility, doc_id=doc_id, extra_meta=extra_meta)
    # 程序到此处的时候，新文件已经彻底被分割并放好元数据


    # 3) 如果overwrite：现在再删旧的chroma chunks（此时新 chunks 已经准备好）
    if existed and overwrite:  # 旧文件要被覆盖，新文件也没问题，要彻底替换
        from app.rag.chroma_admin_kb import delete_by_doc_id
        delete_by_doc_id(doc_id)

    # 4) 写入向量库
    vs = get_vs()
    vs.add_documents(chunks)


    # 5) 更新注册表——此处的注册表只是一个叫法，实际上就是mysql，和windwos的注册表无关

    chroma_cnt = count_by_doc_id(doc_id)

    kb_db.upsert_kb_document(
        doc_id=doc_id,
        original_filename=file.filename,
        stored_path=str(save_path),
        visibility=visibility,
        uploader_user_id=current_user.id,
        uploader_username=current_user.username,
        chunk_count=chroma_cnt,
    )

    # 6) overwrite 时可选删除旧文件（最后一步做）
    deleted_old_file = False
    if delete_old_file and old_path and old_path != str(save_path):
        try:
            p = Path(old_path)
            if p.exists() and p.is_file():  # p.is_file是担心对文件夹有影响
                p.unlink()  # unlink想像成为删除文件
                deleted_old_file = True
        except Exception:
            deleted_old_file = False

    return {
        "saved_as": str(save_path),
        "visibility": visibility,
        "doc_id": doc_id,
        "chunks": chroma_cnt,
        "overwrote": bool(existed and overwrite),
        "deleted_old_file": deleted_old_file,
    }




@app.post("/reindex")
def reindex(visibility_default: str = Form("public"),
            current_user=Depends(get_current_user)):
    """
       文档入库：需要 kb.manage_docs 权限
       """
    check_permission(current_user, "kb.manage_docs")
    visibility_default = (visibility_default or "public").strip().lower()

    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    try:
        client.delete_collection(settings.collection_name)
    except Exception as e:
        return {
            "success": False,
            "message": "重建索引失败：无法删除旧的向量集合",
            "error": str(e)
        }
    client.get_or_create_collection(settings.collection_name)

    vs = get_vs()
    raw_docs = load_docs(str(DATA_DOCS_DIR))
    if not raw_docs:
        return {"chunks": 0, "docs": 0, "message": "No documents found in data/docs"}

    chunks = split_docs(raw_docs)
    for c in chunks:
        c.metadata = dict(c.metadata or {})
        c.metadata.setdefault("visibility", visibility_default)

    vs.add_documents(chunks)

    return {"docs": len(raw_docs), "chunks": len(chunks), "visibility_default": visibility_default}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.workflows.main:app", host="127.0.0.1", port=8003,reload=True)
