import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from main import (
    clean_ai_output,
    fix_c_java_foreach_initializer_list,
    fix_javascript_inject_simple_int_decls,
    fix_python_java_style_print_concat,
    strip_c_conversion_hallucinations,
)
from output_validator import collect_post_conversion_warnings, format_validation_warnings, is_balanced, validate_with_tree_sitter


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


def test_golden_source_passes_hard_validation():
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_with_tree_sitter(payload["source_code"], payload["source_lang"], stage="source")


def test_collect_warnings_detects_java_foreach_in_c():
    bad = "int main(){ for(int n : {1,2}) printf(\"%d\", n); return 0; }"
    ws = collect_post_conversion_warnings(bad, "c")
    assert any("Java-style" in w for w in ws)


def test_fix_c_java_foreach_produces_parseable_c():
    raw = """
#include <stdio.h>
int main() {
for(int num : {
    5, 10, 15
})
printf("%d", num);
return 0;
}
"""
    fixed = fix_c_java_foreach_initializer_list(raw)
    validate_with_tree_sitter(fixed, "c", stage="output")


def test_fix_python_print_concat_avoids_str_int_error_pattern():
    line = 'print("Value of a: " + a)'
    out = fix_python_java_style_print_concat(line)
    assert "print(" in out and ", a)" in out and "+" not in out


def test_strip_c_hallucination_removes_java_banner():
    raw = 'printf("ok");\nprintf("Java test completed successfully!");\n'
    out = strip_c_conversion_hallucinations(raw)
    assert "Java test completed" not in out
    assert "printf(\"ok\")" in out


def test_js_inject_let_from_c_int_locals():
    c = """#include <stdio.h>
int main() {
    int a = 10;
    int b = 20;
    int sum = a + b;
    printf("%d\\n", sum);
    return 0;
}
"""
    js = 'console.log(a);\nconsole.log(b);\nconsole.log(a + b);\n'
    out = fix_javascript_inject_simple_int_decls(js, c)
    assert "let a = 10" in out
    assert "let b = 20" in out
    assert "let sum = a + b" in out
    assert out.index("let a") < out.index("console.log")


def test_format_validation_warnings_joins():
    s = format_validation_warnings(["a", "b"])
    assert s.startswith("Validation:")
    assert "a" in s and "b" in s
