#Chroma数据库连接：建立与Chroma向量数据库的HTTP客户端连接
import chromadb
from langchain_chroma import Chroma
from app.workflows.config import settings

import chromadb
from langchain_chroma import Chroma
from app.workflows.config import settings

def get_client():
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port
    )

def get_vectorstore(embeddings):
    return Chroma(
        client=get_client(),
        collection_name=settings.collection_name,
        embedding_function=embeddings,
    )

def get_audio_vectorstore(embeddings):
    return Chroma(
        client=get_client(),
        collection_name=settings.audio_collection_name,
        embedding_function=embeddings,
    )
