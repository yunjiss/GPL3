from sentence_transformers import SentenceTransformer

# Google Embedding API → 로컬 KR-SBERT 대체
# jhgan/ko-sroberta-multitask: 한국어 문장 유사도에 최적화된 공개 모델
# API 비용 0원, CPU에서 수십 ms 처리
_model = None


def _load():
    global _model
    if _model is None:
        _model = SentenceTransformer("jhgan/ko-sroberta-multitask")
    return _model


def get_embedding(text: str) -> list[float]:
    return _load().encode(text, convert_to_numpy=True).tolist()
