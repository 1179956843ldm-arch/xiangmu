from app.workflows.deps import get_vs
from app.ingestion.loader import split_docs, load_docs
#todo 是在做一个 文档入库和向量化索引 的流程，
# 这段代码的作用是从指定目录加载文档内容，经过拆分后建立其向量索引并保存至向量数据库中。
def main():
    docs = split_docs(load_docs("./data/docs"))
    vs = get_vs()
    vs.add_documents(docs)
    try:
        vs.persist()
    except Exception:
        pass
    print(f"indexed{len(docs)}chunks into Chroma.")
if __name__ == "__main__":

    main()