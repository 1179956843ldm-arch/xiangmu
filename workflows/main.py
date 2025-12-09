import time
import uuid
from typing import Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from app.ingestion.loader import load_single_file, split_with_visibility, load_docs, split_docs
from workflows.config import settings
import chromadb
from app.ingestion.loader import load_single_file, split_with_visibility
from workflows.deps import get_vs,get_embeddings
from workflows.router_graph import router_graph

app = FastAPI(title="Enterprise KB Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 本地开发可以先全开，线上再收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
DATA_DOCS_DIR = Path("../data/docs")
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

@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq):
    payload = req.model_dump()
    sid = payload.get("session_id")

    if sid and sid in SESSIONS:
        prev = SESSIONS[sid]
        merged = {**prev, **payload}
        merged["text"] = payload.get("text")
        payload = merged

    out = router_graph.invoke(payload)

    if sid:
        SESSIONS[sid] = {**payload, **out}

    return {"answer": out["answer"]}


@app.post("/ingest")
async def ingest(file:UploadFile = File(...),
                 visibility: str = Form("public"),
                 doc_id:Optional[ str] = Form(None)):


    if not file.filename:
        raise HTTPException(status_code=400, detail="Empty filename")
    visibility = (visibility or "public").strip().lower()
    suffix = Path(file.filename).suffix
    safe_name =  f"{int(time.time())}_{uuid.uuid4().hex}{suffix}"
    save_path =  DATA_DOCS_DIR / safe_name
    content = await file.read()


    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    save_path.write_bytes(content)
    docs = load_single_file(save_path)


    if not docs:
        raise HTTPException(status_code=400, detail=f"Unsupported or empty file type: {suffix}")
    chunks = split_with_visibility(docs, visibility=visibility, doc_id=doc_id)
    vs = get_vs()
    vs.add_documents(chunks)


    return {"saved_as":str(save_path),
            "visibility":visibility,
            "doc_id":doc_id,
            "chunks":len(chunks),}
@app.post("/reindex")
def reindex(visibility_default: str = Form("public")):
    visibility_default = (visibility_default or "public").strip().lower()

    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    try:
        client.delete_collection(settings.collection_name)
    except Exception:
        print('================删除chromadb报错了')
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
    uvicorn.run("main:app", host="127.0.0.1", port=8002,reload=True)
