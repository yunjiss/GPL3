import chromadb

# SQLite: 일기 메타데이터 / ChromaDB: 임베딩 벡터 — 역할 분리
_client = chromadb.PersistentClient(path="./chroma_db")
_collection = _client.get_or_create_collection(
    name="diaries",
    metadata={"hnsw:space": "cosine"},  # 코사인 거리 기반 유사도 검색
)


def add(diary_id: int, embedding: list[float], metadata: dict) -> None:
    _collection.add(
        ids=[str(diary_id)],
        embeddings=[embedding],
        metadatas=[metadata],
    )


def delete(diary_id: int) -> None:
    try:
        _collection.delete(ids=[str(diary_id)])
    except Exception:
        pass


def find_similar(embedding: list[float], n_results: int = 3) -> list[dict]:
    count = _collection.count()
    if count == 0:
        return []

    results = _collection.query(
        query_embeddings=[embedding],
        n_results=min(n_results, count),
        include=["metadatas", "distances"],
    )

    return [
        {**meta, "similarity": round(1 - dist, 4)}
        for meta, dist in zip(
            results["metadatas"][0], results["distances"][0]
        )
    ]
