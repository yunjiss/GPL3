from transformers import pipeline

# KoELECTRA-small fine-tuned on MODU NER corpus
# MODU 태그: PS(인물), LC(장소), OG(기관), AF(인공물), DT(날짜) 등
# 모델이 없으면 HuggingFace에서 대체 모델 검색:
#   https://huggingface.co/models?language=ko&pipeline_tag=token-classification
_NER_MODEL = "Leo97/KoELECTRA-small-v3-modu-ner"

_ner = None


def _load():
    global _ner
    if _ner is None:
        _ner = pipeline(
            "token-classification",
            model=_NER_MODEL,
            aggregation_strategy="simple",
            device=-1,
        )
    return _ner


def extract_persons(text: str) -> list[str]:
    try:
        results = _load()(text)
        return list({
            r["word"].strip()
            for r in results
            if r["entity_group"] in ("PS", "PER") and len(r["word"].strip()) > 1
        })
    except Exception:
        # NER 모델 로드 실패 시 빈 리스트로 graceful degradation
        # Vertex AI 분석 단계에서 텍스트로부터 인물을 보완 추출함
        return []
