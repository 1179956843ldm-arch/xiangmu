from fastapi import FastAPI
from pydantic import BaseModel
from app.router_graph import router_graph

app = FastAPI(title="Enterprise KB Assistant")

class ChatReq(BaseModel):
    text: str
    user_role: str = "public"
    requester: str = "anonymous"

class ChatResp(BaseModel):
    answer: str

@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq):
    out = router_graph.invoke(req.model_dump())
    return {"answer": out["answer"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8002,reload=True)
