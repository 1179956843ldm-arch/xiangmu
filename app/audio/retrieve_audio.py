from __future__ import annotations

from typing import List

from app.workflows.deps import get_vs, get_audio_vs
from app.service.rbac_service import allowed_kb_visibilities

#todo 音频相似度搜索（vector similarity search）
def audio_similarity_search_for_user(query: str, user, k: int = 6):
    vs = get_audio_vs()
    docs = vs.similarity_search(query, k=k, filter={"visibility": {"$in":['public']}})
    return docs, ['public']

# vs.similarity_search(...) → 用向量搜索找到最相似的文档/音频
# k=k → 返回前 k 条结果
# filter={"visibility": {"$in":['public']}} → 只搜索 可见性为 public 的内容
# $in 是 MongoDB 风格的语法
# 可扩展为 ['public','internal','hr'] 这样可以根据用户权限筛选
