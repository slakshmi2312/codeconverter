import os
from dataclasses import dataclass

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


DEFAULT_CODET5_MODEL = "Salesforce/codet5-base"


@dataclass
class CodeT5Bundle:
    tokenizer: AutoTokenizer
    model: AutoModelForSeq2SeqLM
    device: torch.device


def get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def model_name_or_path() -> str:
    return (os.getenv("CODET5_MODEL_PATH") or DEFAULT_CODET5_MODEL).strip()


def load_codet5(model_path: str | None = None) -> CodeT5Bundle:
    chosen = model_path or model_name_or_path()
    tokenizer = AutoTokenizer.from_pretrained(chosen)
    model = AutoModelForSeq2SeqLM.from_pretrained(chosen)
    device = get_device()
    model.to(device)
    model.eval()
    return CodeT5Bundle(tokenizer=tokenizer, model=model, device=device)
