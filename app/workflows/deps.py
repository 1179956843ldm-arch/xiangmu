from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_openai import ChatOpenAI
from app.workflows.config import settings
from app.rag.vectorstore import get_vectorstore, get_audio_vectorstore


# 统一管理AI模型依赖：集中配置和提供大语言模型、嵌入模型等核心AI组件

def get_llm():
    """创建并返回一个配置好的 DeepSeek Chat 模型实例，用于对话生成"""
    return ChatOpenAI(
        model=settings.model_name,  # DeepSeek 对应的模型名称
        api_key=settings.openai_api_key,  # 复用现有的 API Key 配置
        base_url=settings.base_url,  # DeepSeek API 地址
        temperature=0.2,
        streaming=True,
    )



    # 创建并返回一个 OpenAIEmbeddings 实例，用于文本向量化处理
def get_embeddings():
    return ZhipuAIEmbeddings(
        model=settings.embedding_model_name,
        api_key=settings.zhipu_api_key
    )


def get_vs():                           #创建并返回向量存储实例
    return get_vectorstore(get_embeddings())




def get_audio_vs():
    return get_audio_vectorstore(get_embeddings())



if __name__ == "__main__":
    print("------------")
    print(get_llm())
    print("------------")
    print(get_embeddings())
    print("------------")
    print(get_vs())
    print("------------")