"""vector_db.py — ChromaDB 래퍼 (user_id 필터링 지원)"""

import chromadb

_client     = chromadb.PersistentClient(path="./chroma_db")
_collection = _client.get_or_create_collection(
    name="diaries",
    metadata={"hnsw:space": "cosine"},
)


def add(diary_id: int, embedding: list[float], metadata: dict) -> None:
    meta = {**metadata}
    if "user_id" in meta:
        meta["user_id"] = str(meta["user_id"])
    _collection.add(
        ids=[str(diary_id)],
        embeddings=[embedding],
        metadatas=[meta],
    )


def delete(diary_id: int) -> None:
    try:
        _collection.delete(ids=[str(diary_id)])
    except Exception:
        pass


def find_similar(
    embedding: list[float],
    user_id: int | None = None,
    n_results: int = 3,
) -> list[dict]:
    count = _collection.count()
    if count == 0:
        return []

    n = min(n_results, count)
    kwargs: dict = {
        "query_embeddings": [embedding],
        "n_results":        n,
        "include":          ["metadatas", "distances"],
    }
    if user_id is not None:
        kwargs["where"] = {"user_id": str(user_id)}

    try:
        res = _collection.query(**kwargs)
    except Exception:
        # 기존 데이터에 user_id 없는 경우 전체 검색으로 폴백
        kwargs.pop("where", None)
        try:
            res = _collection.query(**kwargs)
        except Exception:
            return []

    return [
        {**meta, "similarity": round(1 - dist, 4)}
        for meta, dist in zip(res["metadatas"][0], res["distances"][0])
    ]
