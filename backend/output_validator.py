"""
Post-conversion validation: syntax checks, heuristics for common bad patterns,
and optional strict mode (raises) for tests and CI.
"""

from __future__ import annotations

import ast
import re
from typing import List

from fastapi import HTTPException
from tree_sitter_languages import get_parser

_TS_LANG = {
    "python": "python",
    "java": "java",
    "c": "c",
    "javascript": "javascript",
}


def is_balanced(text: str) -> bool:
    """Rough () {} [] balance check; ignores characters inside double-quoted strings."""
    stack: List[str] = []
    pairs = {")": "(", "}": "{", "]": "["}
    openers = set("({[")
    closers = set(")}]")
    in_dquote = False
    escape = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_dquote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_dquote = False
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            i += 1
            continue
        if ch in openers:
            stack.append(ch)
        elif ch in closers:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
        i += 1
    return not stack and not in_dquote


def _tree_sitter_has_error(code: str, language: str) -> bool:
    parser = get_parser(_TS_LANG[language])
    tree = parser.parse((code or "").encode("utf-8", errors="ignore"))
    return bool(tree.root_node.has_error)


def validate_with_tree_sitter(code: str, language: str, *, stage: str = "output") -> None:
    """
    Hard validation for tests: raises HTTPException 400 if syntax is invalid.
    Python uses ast.parse; other languages use tree-sitter error flag.
    """
    lang = (language or "").strip().lower()
    if lang not in _TS_LANG:
        raise HTTPException(status_code=400, detail=f"Unknown language '{language}' for validation.")

    if lang == "python":
        try:
            ast.parse(code or "")
        except SyntaxError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Python {stage} syntax error: {exc.msg} at line {getattr(exc, 'lineno', '?')}.",
            ) from exc
        return

    if _tree_sitter_has_error(code, lang):
        raise HTTPException(
            status_code=400,
            detail=f"{lang} {stage} has parse errors (invalid syntax).",
        )


def collect_post_conversion_warnings(code: str, target_lang: str) -> List[str]:
    """
    Non-throwing checks after sanitization. Returns human-readable warning strings.
    """
    warnings: List[str] = []
    lang = (target_lang or "").strip().lower()
    text = code or ""

    if not text.strip():
        warnings.append("Converted output is empty.")
        return warnings

    # --- Syntax layer ---
    if lang == "python":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            warnings.append(f"Python syntax error after conversion: {exc.msg} (line {getattr(exc, 'lineno', '?')}).")
    elif lang in _TS_LANG:
        if _tree_sitter_has_error(text, lang):
            warnings.append(f"{lang.title()} syntax may be invalid (tree-sitter reported parse errors).")

    # --- Heuristic layer (common model mistakes) ---
    if lang == "python":
        if re.search(r'print\s*\(\s*"[^"]*"\s*\+\s*[A-Za-z_]\w*\s*\)', text):
            warnings.append(
                "Possible str+int in print(); use print(\"text:\", value) or an f-string to avoid TypeError."
            )

    if lang == "c":
        if re.search(r"for\s*\(\s*int\s+\w+\s*:\s*", text):
            warnings.append("Java-style 'for (int x : ...)' is not valid C; use indexed loops over an array.")

    if lang == "java":
        if "class" not in text and "interface" not in text and "enum" not in text:
            warnings.append("Java output may be missing a class/interface wrapper for full programs.")

    if not is_balanced(text):
        warnings.append("Brackets or parentheses may be unbalanced in the converted output.")

    return warnings


def format_validation_warnings(items: List[str]) -> str:
    if not items:
        return ""
    return "Validation: " + " | ".join(items)
