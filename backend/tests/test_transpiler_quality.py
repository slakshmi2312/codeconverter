import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from main import clean_ai_output, is_balanced, validate_with_tree_sitter


GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.parametrize(
    "lang,code",
    [
        ("python", "for i in range(3):\n    print(i)\n"),
        ("java", "public class Main { public static void main(String[] args) { System.out.println(1); } }"),
        ("c", "#include <stdio.h>\nint main(){ printf(\"x\\n\"); return 0; }"),
        ("javascript", "for (let i = 0; i < 2; i++) { console.log(i); }"),
    ],
)
def test_ast_validation_source_ok(lang, code):
    validate_with_tree_sitter(code, lang, stage="source")


def test_ast_validation_raises_on_broken_python():
    with pytest.raises(HTTPException):
        validate_with_tree_sitter("for i in range(3)\nprint(i)", "python", stage="source")


def test_clean_output_strips_markdown_and_python_semicolons():
    raw = "```python\nprint('hi');\n```"
    cleaned = clean_ai_output(raw, "python")
    assert cleaned == "print('hi')"


def test_balance_checker():
    assert is_balanced("function x(){ return (1+2); }")
    assert not is_balanced("function x(){ return (1+2; }")


@pytest.mark.parametrize("path", sorted(GOLDEN_DIR.glob("*.json")))
def test_golden_cases_have_valid_shapes(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source_lang"] in {"python", "java", "c", "javascript"}
    assert payload["target_lang"] in {"python", "java", "c", "javascript"}
    assert isinstance(payload["source_code"], str) and payload["source_code"].strip()
    assert isinstance(payload["expected_contains"], list) and payload["expected_contains"]
