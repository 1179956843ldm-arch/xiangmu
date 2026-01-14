from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    base_url:str = "https://api.deepseek.com/v1"
    dashscope_api_key: str = os.getenv("DASH_SCOPE_API_KEY", "")
    openai_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    model_name: str = os.getenv("MODEL_NAME", "deepseek-chat")
    chroma_dir: str = os.getenv("CHROMA_DIR", "./data/chroma")
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    collection_name: str = os.getenv("COLLECTION_NAME", "knowledge_base")
    audio_collection_name:str = os.getenv("AUDIO_COLLECTION_NAME", "audio_base")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "120"))
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "amqp://ldm:123@127.0.0.1:5672/%2F") # ⚠️改自己的用户名和密码
    celery_audio_queue: str = "audio"  # 消息队列的名字

    audio_dir: str = r"/home/ldm/PycharmProjects/enterprise-kb-assistant/data/audio"
    audio_wav_dir: str = r"/home/ldm/PycharmProjects/enterprise-kb-assistant/data/audio_wav"
    audio_clip_dir: str = r"/home/ldm/PycharmProjects/enterprise-kb-assistant/data/audio_clips"
    
    zhipu_base_url: str = os.getenv("ZHIPU_BASE_URL", "")
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "")
    embedding_model_name: str = os.getenv("EMBEDDING_MODEL_NAME", "embedding-3")
    ALLOWED_VISIBILITIES: set[str] = {"public", "internal", "hr", "it"}

    es_url: str = os.getenv("ES_URL", "http://127.0.0.1:9200")
    es_audio_index: str = os.getenv("ES_AUDIO_INDEX", "audio_segments_v1")

    audio_hybrid_top_v: int = int(os.getenv("AUDIO_HYBRID_TOP_V", "50"))
    audio_hybrid_top_b: int = int(os.getenv("AUDIO_HYBRID_TOP_B", "50"))
    audio_hybrid_top_n_rerank: int = int(os.getenv("AUDIO_HYBRID_TOP_N_RERANK", "30"))
    audio_rrf_k0: int = int(os.getenv("AUDIO_RRF_K0", "60"))

    audio_rerank_model: str = os.getenv("AUDIO_RERANK_MODEL", "BAAI/bge-reranker-base")
    audio_rerank_batch_size: int = int(os.getenv("AUDIO_RERANK_BATCH_SIZE", "16"))
    audio_rerank_max_len: int = int(os.getenv("AUDIO_RERANK_MAX_LEN", "512"))
    audio_rerank_min_score: float = float(os.getenv("AUDIO_RERANK_MIN_SCORE", "-1e9"))
settings = Settings()
