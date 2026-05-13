import re
from dataclasses import dataclass
from typing import Optional

import torch

from ast_parser import ast_feature_dict
from model_utils import CodeT5Bundle, load_codet5


def _clean_output(text: str) -> str:
    out = (text or "").strip()
    out = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", out)
    out = re.sub(r"\n?```$", "", out)
    out = out.replace("<pad>", "").replace("</s>", "").replace("<s>", "")
    out = re.sub(r"\s+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


@dataclass
class InferenceResult:
    converted_code: str
    used_model: str
    prompt: str


class CodeT5InferenceEngine:
    def __init__(self, bundle: Optional[CodeT5Bundle] = None):
        self.bundle = bundle or load_codet5()

    def _build_prompt(self, code: str, source_lang: str, target_lang: str) -> str:
        ast_info = ast_feature_dict(code, source_lang)
        ast_hint = (
            f"ast_root={ast_info['root_type']} "
            f"node_count={ast_info['node_count']} "
            f"max_depth={ast_info['max_depth']}"
        )
        return f"translate {source_lang} to {target_lang}: {ast_hint}\n{code}"

    def translate(self, code: str, source_lang: str, target_lang: str) -> InferenceResult:
        prompt = self._build_prompt(code, source_lang, target_lang)
        inputs = self.bundle.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        inputs = {k: v.to(self.bundle.device) for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self.bundle.model.generate(
                **inputs,
                max_length=512,
                num_beams=4,
                early_stopping=True,
            )

        decoded = self.bundle.tokenizer.decode(output_ids[0], skip_special_tokens=True)
        cleaned = _clean_output(decoded)
        return InferenceResult(
            converted_code=cleaned,
            used_model=getattr(self.bundle.model.config, "_name_or_path", "codet5"),
            prompt=prompt,
        )
