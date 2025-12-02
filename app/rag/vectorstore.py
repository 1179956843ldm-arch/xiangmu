#Chroma数据库连接：建立与Chroma向量数据库的HTTP客户端连接
import chromadb
from langchain_chroma import Chroma
from app.config import settings

def get_vectorstore(embeddings):                                #过 get_vectorstore 函数创建并返回 Chroma 实例
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )
    return Chroma(
        client=client,
        collection_name=settings.collection_name,
        embedding_function=embeddings,
    )