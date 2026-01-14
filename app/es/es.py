from __future__ import annotations


from functools import lru_cache
from elasticsearch import Elasticsearch
from app.workflows.config import settings


AUDIO_INDEX = getattr(settings, "es_audio_index", "audio_segments_v1")
# ES中的索引名字，读取es_audio_index的值，没有就取audio_segments_v1

@lru_cache(maxsize=1)
def es_client() -> Elasticsearch:
    return Elasticsearch(
        hosts=[settings.es_url],
        request_timeout=30,
        retry_on_timeout=True,
        max_retries=3,
    )






