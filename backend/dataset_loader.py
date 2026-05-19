import json
import re
from pathlib import Path
from typing import Dict, Iterable, List

from datasets import Dataset


def _strip_comments(code: str, lang: str) -> str:
    if not code:
        return ""

    text = code
    if lang in {"python"}:
        text = re.sub(r"(?m)#.*$", "", text)
        text = re.sub(r"(?s)'''[\s\S]*?'''", "", text)
        text = re.sub(r'(?s)"""[\s\S]*?"""', "", text)
    else:
        text = re.sub(r"(?m)//.*$", "", text)
        text = re.sub(r"(?s)/\*[\s\S]*?\*/", "", text)

    return text


def _normalize_indentation(code: str) -> str:
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized = []
    for line in lines:
        line = line.replace("\t", "    ").rstrip()
        normalized.append(line)
    return "\n".join(normalized).strip()


def _collapse_whitespace(code: str) -> str:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in code.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def _light_tokenize(code: str) -> str:
    # Lightweight, language-agnostic token spacing to stabilize training data.
    code = re.sub(r"([{}()[\];,])", r" \1 ", code)
    code = re.sub(r"\s+", " ", code).strip()
    return code


def preprocess_code(code: str, lang: str, tokenize: bool = True) -> str:
    text = _strip_comments(code, lang)
    text = _normalize_indentation(text)
    text = _collapse_whitespace(text)
    if tokenize:
        text = _light_tokenize(text)
    return text


def load_jsonl_records(path: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        records.append(row)
    return records


def build_codet5_dataset(records: Iterable[Dict[str, str]]) -> Dataset:
    rows = []
    for item in records:
        src_lang = (item.get("source_lang") or "").lower().strip()
        tgt_lang = (item.get("target_lang") or "").lower().strip()
        src_code = preprocess_code(item.get("source_code", ""), src_lang, tokenize=False)
        tgt_code = preprocess_code(item.get("target_code", ""), tgt_lang, tokenize=False)
        prompt = f"translate {src_lang} to {tgt_lang}: {src_code}"
        rows.append(
            {
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "source_code": src_code,
                "target_code": tgt_code,
                "input_text": prompt,
                "target_text": tgt_code,
            }
        )
    return Dataset.from_list(rows)
