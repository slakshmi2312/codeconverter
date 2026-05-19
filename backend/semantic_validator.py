from difflib import SequenceMatcher
from typing import Dict

from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ast_parser import ast_feature_dict


def _safe_cosine(a: str, b: str) -> float:
    if not a.strip() or not b.strip():
        return 0.0
    vectorizer = CountVectorizer(token_pattern=r"[^ ]+")
    mat = vectorizer.fit_transform([a, b])
    return float(cosine_similarity(mat[0], mat[1])[0][0])


def semantic_similarity_score(
    source_code: str,
    source_lang: str,
    translated_code: str,
    target_lang: str,
) -> Dict[str, object]:
    src = ast_feature_dict(source_code, source_lang)
    tgt = ast_feature_dict(translated_code, target_lang)

    src_tokens = " ".join(src["node_types"])
    tgt_tokens = " ".join(tgt["node_types"])

    seq_ratio = SequenceMatcher(None, src_tokens, tgt_tokens).ratio()
    cos_ratio = _safe_cosine(src_tokens, tgt_tokens)

    score = int(round(((seq_ratio * 0.55) + (cos_ratio * 0.45)) * 100))
    score = max(0, min(100, score))

    return {
        "semantic_score": score,
        "source_ast": src,
        "target_ast": tgt,
    }
