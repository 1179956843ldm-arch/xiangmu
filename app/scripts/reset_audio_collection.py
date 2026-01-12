import os
import chromadb

def main():
    host = os.getenv("CHROMA_HOST", "localhost")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    name = os.getenv("AUDIO_COLLECTION_NAME", "audio_base")

    client = chromadb.HttpClient(host=host, port=port)
    client.delete_collection(name=name)
    col = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )

if __name__ == "__main__":
    main()