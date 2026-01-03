from __future__ import annotations

from typing import List

from app.workflows.deps import get_vs, get_audio_vs
from app.service.rbac_service import allowed_kb_visibilities


def audio_similarity_search_for_user(query: str, user, k: int = 6):
    vs = get_audio_vs()
    docs = vs.similarity_search(query, k=k, filter={"visibility": {"$in":['public']}})
    return docs, ['public']


