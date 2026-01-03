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

    audio_dir: str = "data/audio"
    audio_wav_dir: str = "data/audio_wav"
    audio_clip_dir: str = "data/audio_clips"
    
    zhipu_base_url: str = os.getenv("ZHIPU_BASE_URL", "")
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "")
    embedding_model_name: str = os.getenv("EMBEDDING_MODEL_NAME", "embedding-3")
    ALLOWED_VISIBILITIES: set[str] = {"public", "internal", "hr", "it"}
settings = Settings()
