import logging
import os
import re
import time
from typing import Dict, Optional, Tuple

import requests

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field
from ast_parser import ast_feature_dict
from inference import CodeT5InferenceEngine
from language_detector import MLLanguageDetector
from output_validator import collect_post_conversion_warnings, format_validation_warnings
from semantic_validator import semantic_similarity_score

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================
# Aash Gates Rescue Build
# Provider: OpenRouter API
# API shape: OpenAI-compatible Chat Completions
# ============================================================

EXTENSION_MAP = {
    ".c": "c",
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
}

SUPPORTED_LANGUAGES = {"python", "java", "c", "javascript"}

# For demo, openrouter/free is easiest. You can replace it with any OpenRouter model.
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AI_TIMEOUT_SECONDS = 20

LANG_HINTS: Dict[Tuple[str, str], str] = {
    ("java", "python"): "Convert Java types, braces, main method, and System.out.println into clean Python. Use print with commas for mixed types (e.g. print(\"x:\", n)), not string + int concatenation. For loops like for (int i=1; i<=N; i++) use range(1, N+1) in Python.",
    ("python", "java"): "Wrap code inside public class Main and public static void main where needed.",
    ("c", "python"): "Convert printf/scanf, loops, arrays, and main function into simple Python.",
    ("python", "c"): "Create a complete C program with #include <stdio.h> and int main where needed.",
    ("javascript", "python"): "Convert console.log, let/const/var, braces, and JS loops into Python.",
    ("python", "javascript"): "Convert print, indentation blocks, and Python lists into JavaScript syntax.",
    ("java", "javascript"): "Convert Java classes and System.out.println into JavaScript classes or simple functions.",
    ("javascript", "java"): "Convert console.log and JS syntax into Java with class Main where needed.",
    ("c", "javascript"): "Map C int locals to let/const in JavaScript before using them. Preserve every simple `int name = value;` as `let name = value;`. Use console.log with commas for mixed types. Use for (let i = ...) loops; arrays as const a = [...].",
    ("c", "java"): "Convert C main, printf, primitive variables, and loops into Java class Main.",
    ("java", "c"): "Convert Java main, System.out.println, primitive variables, and loops into C main. C has NO range-for over arrays: use int arr[] = {...}; for (int i = 0; i < n; i++) { int x = arr[i]; ... }. Use printf with \\n for line-oriented output.",
}

MASTER_PROMPT = """You are a strict code transpiler.

Convert SOURCE_LANGUAGE code into TARGET_LANGUAGE code.

Rules:
1. Return ONLY target language code.
2. Do NOT add explanation, markdown, comments about conversion, or code fences.
3. Do NOT mix source language syntax into target language.
4. Preserve the same logic and output.
5. Keep the output simple and runnable.
6. Prefer beginner-friendly code over clever code.
7. If the input is a small demo program, return a small complete runnable target program.
"""


class ConvertRequest(BaseModel):
    code: str = Field(min_length=1)
    source_lang: Optional[str] = None
    target_lang: str
    filename: Optional[str] = None


class ConvertResponse(BaseModel):
    converted_code: str
    provider: str = "openrouter"
    model: str
    mode: str = "hybrid-rule-ai"
    warning: Optional[str] = None
    iterations: int = 1
    semantic_score: int = 0
    execution_output: str = ""
    execution_error: Optional[str] = None
    status: str = "success"


class CompileRequest(BaseModel):
    code: str = Field(min_length=1)
    language: str


class CompileResponse(BaseModel):
    success: bool
    output: str


class RunRequest(BaseModel):
    code: str = Field(min_length=1)
    language: str


class RunResponse(BaseModel):
    output: str
    error: Optional[str] = None


class DetectLanguageRequest(BaseModel):
    code: str = Field(min_length=1)


class DetectLanguageResponse(BaseModel):
    language: str
    confidence: float
    method: str = "ml"


JUDGE0_LANGUAGE_IDS = {
    "python": 71,
    "javascript": 63,
    "c": 50,
    "java": 62,
}


def detect_language(filename: Optional[str]) -> str:
    if not filename:
        return "unknown"
    lowered = filename.lower()
    for ext, lang in EXTENSION_MAP.items():
        if lowered.endswith(ext):
            return lang
    return "unknown"


def detect_language_from_code(code: str) -> str:
    text = code or ""
    if re.search(r"System\.out\.println|public\s+static\s+void\s+main|public\s+class\s+\w+", text):
        return "java"
    if re.search(r"#include\s*<|printf\s*\(|scanf\s*\(|\bmalloc\s*\(", text):
        return "c"
    if re.search(r"def\s+\w+\s*\(|if\s+__name__\s*==\s*[\"']__main__[\"']|print\s*\(", text):
        return "python"
    if re.search(r"function\s+\w+\s*\(|console\.log|=>", text):
        return "javascript"
    return "unknown"


def normalize_language(lang: Optional[str]) -> str:
    value = (lang or "").strip().lower()
    aliases = {
        "py": "python",
        "js": "javascript",
        "node": "javascript",
        "cpp": "c",
    }
    value = aliases.get(value, value)
    if value not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{lang}'. Supported: python, java, c, javascript.",
        )
    return value


def preprocess(code: str) -> str:
    code = code.replace("\r\n", "\n")
    code = re.sub(r"```[a-zA-Z0-9_-]*", "", code)
    code = code.replace("```", "")
    return code.strip()


def clean_ai_output(text: str, target_lang: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    lines = cleaned.splitlines()
    while lines and lines[0].strip().lower().startswith(("here", "sure", "converted", "output:")):
        lines.pop(0)
    cleaned = "\n".join(lines).strip()
    if target_lang == "python":
        cleaned = re.sub(r";+\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


# ============================================================
# Lightweight rule-based conversion layer
# This is NOT meant to replace AI. It improves demo stability.
# ============================================================

def rule_based_preconvert(code: str, source_lang: str, target_lang: str) -> str:
    text = code.strip()

    if source_lang == "java" and target_lang == "python":
        # Remove common Java wrappers for tiny demo programs.
        text = re.sub(r"public\s+class\s+\w+\s*\{", "", text)
        text = re.sub(r"public\s+static\s+void\s+main\s*\([^)]*\)\s*\{", "", text)
        text = text.replace("System.out.println", "print")
        text = re.sub(r"\b(int|float|double|long|String|boolean|char)\s+(\w+)\s*=", r"\2 =", text)
        text = text.replace(";", "")
        text = text.replace("{", ":")
        text = text.replace("}", "")

    elif source_lang == "python" and target_lang == "java":
        # Give AI cleaner intent for basic prints.
        text = text.replace("print(", "System.out.println(")

    elif source_lang == "c" and target_lang == "python":
        text = re.sub(r"#include\s*<[^>]+>\s*", "", text)
        text = re.sub(r"int\s+main\s*\(\s*\)\s*\{", "", text)
        text = re.sub(r"return\s+0\s*;", "", text)
        text = re.sub(r'printf\("%[difsclu]+\\n",\s*([^)]*)\);', r"print(\1)", text)
        text = re.sub(r'printf\("(.*?)"\);', r'print("\1")', text)
        text = re.sub(r"\b(int|float|double|long|char)\s+(\w+)\s*=", r"\2 =", text)
        text = text.replace(";", "")
        text = text.replace("{", ":")
        text = text.replace("}", "")

    elif source_lang == "javascript" and target_lang == "python":
        text = text.replace("console.log", "print")
        text = re.sub(r"\b(let|const|var)\s+", "", text)
        text = text.replace(";", "")
        text = text.replace("{", ":")
        text = text.replace("}", "")

    return text.strip()


def _split_plus_outside_strings(text: str) -> list[str]:
    """Split on '+' only outside quoted regions (handles \" and \\ inside double-quoted strings)."""
    text = text.strip()
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    in_quote: Optional[str] = None
    while i < len(text):
        ch = text[i]
        if in_quote is not None:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in "\"'":
            in_quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "+":
            piece = "".join(buf).strip()
            if piece:
                parts.append(piece)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _is_simple_string_literal(s: str) -> bool:
    s = s.strip()
    return len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]


def _try_rewrite_print_concat_to_comma_args(inner: str) -> Optional[str]:
    """
    Turn print("a" + b + "c" + d) into print("a", b, "c", d) so ints do not need str() (Java-style concat fix).
    Returns None if the expression is not a simple chain of literals + identifiers.
    """
    parts = _split_plus_outside_strings(inner)
    if len(parts) < 2:
        return None
    for p in parts:
        ps = p.strip()
        if not (_is_simple_string_literal(ps) or re.fullmatch(r"[A-Za-z_]\w*", ps)):
            return None
    return ", ".join(p.strip() for p in parts)


def _extract_print_call_args(line: str) -> Optional[Tuple[int, int, str]]:
    """If line is a single print(...), return (start_idx of '(', end_idx after ')', inner_args)."""
    m = re.search(r"\bprint\s*\(", line)
    if not m:
        return None
    open_paren = m.end() - 1
    depth = 0
    i = open_paren
    while i < len(line):
        if line[i] == "(":
            depth += 1
        elif line[i] == ")":
            depth -= 1
            if depth == 0:
                inner = line[open_paren + 1 : i]
                return open_paren, i + 1, inner
        i += 1
    return None


def fix_python_java_style_print_concat(code: str) -> str:
    """Fix TypeError from print(\"...\" + int_var) patterns common in Java→Python conversions."""
    new_lines: list[str] = []
    for line in code.splitlines():
        if "print(" not in line or "+" not in line:
            new_lines.append(line)
            continue
        parsed = _extract_print_call_args(line)
        if not parsed:
            new_lines.append(line)
            continue
        open_paren, end_after_close, inner = parsed
        if "+" not in inner:
            new_lines.append(line)
            continue
        rewritten = _try_rewrite_print_concat_to_comma_args(inner)
        if not rewritten:
            new_lines.append(line)
            continue
        m = re.search(r"\bprint\s*\(", line)
        if not m:
            new_lines.append(line)
            continue
        prefix = line[: m.end()]
        suffix = line[end_after_close:]
        new_lines.append(prefix + rewritten + ")" + suffix)
    return "\n".join(new_lines)


def _consume_next_c_statement(s: str, start: int) -> Tuple[str, int]:
    """From start, skip whitespace then read one C statement (brace block or until `;` at depth 0)."""
    n = len(s)
    i = start
    while i < n and s[i] in " \t\n\r":
        i += 1
    if i >= n:
        return "", i

    if s[i] == "{":
        depth = 1
        buf = [s[i]]
        i += 1
        while i < n and depth > 0:
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
            buf.append(s[i])
            i += 1
        return "".join(buf), i

    paren = 0
    in_quote: Optional[str] = None
    escape = False
    buf: list[str] = []
    while i < n:
        ch = s[i]
        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue
        if in_quote:
            buf.append(ch)
            if ch == "\\":
                escape = True
            elif ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in "\"'":
            in_quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        buf.append(ch)
        i += 1
        if ch == ";" and paren == 0:
            break
    return "".join(buf), i


def fix_c_java_foreach_initializer_list(code: str) -> str:
    """
    Rewrite invalid Java-style `for (int x : { a, b, c })` (not valid C) into a classic indexed for-loop
    and attach the next statement as the loop body.
    """
    pattern = re.compile(
        r"for\s*\(\s*int\s+(\w+)\s*:\s*\{\s*([^}]*?)\s*\}\s*\)",
        re.MULTILINE | re.DOTALL,
    )
    uid = 0
    pos = 0
    parts: list[str] = []
    for m in pattern.finditer(code):
        parts.append(code[pos : m.start()])
        pos = m.end()
        var = m.group(1)
        raw = m.group(2)
        vals = [v.strip() for v in raw.replace("\n", " ").split(",") if v.strip()]
        if not vals:
            parts.append(m.group(0))
            continue
        inner_vals = ", ".join(vals)
        uid += 1
        stmt, stmt_end = _consume_next_c_statement(code, pos)
        pos = stmt_end
        stmt_clean = stmt.strip()
        if not stmt_clean:
            stmt_block = ""
        else:
            indented = "\n".join("        " + ln if ln.strip() else "" for ln in stmt_clean.splitlines())
            stmt_block = f"\n{indented}\n"
        block = (
            f"    int __cc_arr_{uid}[] = {{{inner_vals}}};\n"
            f"    int __cc_n_{uid} = (int)(sizeof(__cc_arr_{uid}) / sizeof(__cc_arr_{uid}[0]));\n"
            f"    for (int __cc_k_{uid} = 0; __cc_k_{uid} < __cc_n_{uid}; __cc_k_{uid}++) {{\n"
            f"        int {var} = __cc_arr_{uid}[__cc_k_{uid}];"
            f"{stmt_block}"
            f"    }}"
        )
        parts.append(block)
    parts.append(code[pos:])
    return "".join(parts)


def strip_c_conversion_hallucinations(code: str) -> str:
    """Remove common model artifacts that are not in the source program."""
    drop_patterns = (
        r"java\s+test\s+completed",
        r"conversion\s+completed\s+successfully",
        r"test\s+completed\s+successfully",
    )
    lines_out: list[str] = []
    for line in code.splitlines():
        low = line.lower()
        if any(re.search(p, low) for p in drop_patterns):
            continue
        lines_out.append(line)
    return "\n".join(lines_out)


def fix_javascript_inject_simple_int_decls(js_code: str, source_code: str) -> str:
    """
    C/Java→JS models often drop top-level `int a = 10;` locals and emit `console.log(a)` first → ReferenceError.
    Prepend `let` lines for simple `int name = rhs;` from the source (skips arrays/sizeof).
    """
    decls: list[Tuple[str, str]] = []
    for m in re.finditer(r"^\s*int\s+(\w+)\s*=\s*([^;]+);\s*$", source_code, re.MULTILINE):
        name, rhs = m.group(1), m.group(2).strip()
        if "[" in rhs or "]" in rhs or "sizeof" in rhs.lower():
            continue
        decls.append((name, rhs))

    if not decls:
        return js_code

    prelude: list[str] = []
    for name, rhs in decls:
        if re.search(rf"\b(let|const|var)\s+{re.escape(name)}\s*=", js_code):
            continue
        prelude.append(f"let {name} = {rhs.strip()};")

    if not prelude:
        return js_code

    return "\n".join(prelude) + "\n" + js_code.strip()


def sanitize_target_output(
    code: str,
    target_lang: str,
    *,
    source_lang: Optional[str] = None,
    source_code: Optional[str] = None,
) -> str:
    out = code.strip()

    if target_lang == "python":
        out = out.replace("System.out.println", "print")
        out = out.replace("console.log", "print")
        out = re.sub(r"\b(int|float|double|long|String|boolean|char)\s+(\w+)\s*=", r"\2 =", out)
        out = re.sub(r";+\s*$", "", out, flags=re.MULTILINE)
        out = fix_python_java_style_print_concat(out)

    elif target_lang == "javascript":
        out = out.replace("System.out.println", "console.log")
        out = re.sub(r"^print\((.*)\)$", r"console.log(\1);", out, flags=re.MULTILINE)
        if source_lang in ("c", "java") and source_code:
            out = fix_javascript_inject_simple_int_decls(out, source_code)

    elif target_lang == "java":
        out = out.replace("console.log", "System.out.println")
        out = re.sub(r"^print\((.*)\)$", r"System.out.println(\1);", out, flags=re.MULTILINE)
        if "public class" not in out:
            # Put loose statements into a Java runnable class.
            body = out
            if "public static void main" not in body:
                body = indent_code(body, "        ")
                out = "public class Main {\n    public static void main(String[] args) {\n" + body + "\n    }\n}"
            else:
                out = "public class Main {\n" + indent_code(body, "    ") + "\n}"

    elif target_lang == "c":
        out = out.replace("System.out.println", "printf")
        out = out.replace("console.log", "printf")
        out = strip_c_conversion_hallucinations(out)
        out = fix_c_java_foreach_initializer_list(out)
        if "#include <stdio.h>" not in out:
            out = "#include <stdio.h>\n\n" + out
        if "int main" not in out:
            body = indent_code(out.replace("#include <stdio.h>", "").strip(), "    ")
            out = "#include <stdio.h>\n\nint main() {\n" + body + "\n    return 0;\n}"

    out = beautify_compact_output(out, target_lang)
    return out.strip()


def indent_code(code: str, spaces: str) -> str:
    lines = [line.rstrip() for line in code.strip().splitlines()]
    return "\n".join(spaces + line if line.strip() else "" for line in lines)


JAVA_CLASS_DECL_RE = re.compile(
    r"(?m)^((?:public\s+)?(?:abstract\s+)?(?:final\s+)?)class\s+(\w+)\b"
)
JAVA_MAIN_METHOD_RE = re.compile(
    r"public\s+static\s+void\s+main\s*\(\s*String(?:\s*\[\s*\])?\s+\w*\s*\)"
)


def _find_java_class_with_main(code: str) -> Optional[str]:
    classes = list(JAVA_CLASS_DECL_RE.finditer(code))
    if not classes:
        return None
    main_match = JAVA_MAIN_METHOD_RE.search(code)
    if not main_match:
        return None
    main_pos = main_match.start()
    for i, match in enumerate(classes):
        start = match.start()
        end = classes[i + 1].start() if i + 1 < len(classes) else len(code)
        if start <= main_pos < end:
            return match.group(2)
    return None


def prepare_java_for_judge0(code: str) -> str:
    """
    Judge0 compiles Java as Main.java and runs `java Main`.
    Ensure the entry class is public class Main and other classes are not public.
    """
    text = code.strip()
    if not text:
        return text

    main_class = _find_java_class_with_main(text)

    text = re.sub(
        r"(?m)^(public\s+)(?=(?:abstract\s+)?(?:final\s+)?class\s+)",
        "",
        text,
    )

    if main_class and main_class != "Main":
        text = re.sub(
            rf"\bclass\s+{re.escape(main_class)}\b",
            "class Main",
            text,
            count=1,
        )
        text = re.sub(rf"\b{re.escape(main_class)}\b", "Main", text)

    if re.search(r"(?m)^class\s+Main\b", text):
        text = re.sub(r"(?m)^class\s+Main\b", "public class Main", text, count=1)

    return text


def beautify_compact_output(code: str, target_lang: str) -> str:
    out = code.strip()
    if not out:
        return out

    if target_lang == "python":
        # Many model responses compress statements with semicolons.
        if "\n" not in out and ";" in out:
            parts = [p.strip() for p in out.split(";") if p.strip()]
            return "\n".join(parts)
        return out

    if target_lang in {"java", "javascript", "c"}:
        return beautify_brace_language(out)

    return out


def beautify_brace_language(code: str) -> str:
    tokens = []
    in_string = False
    string_quote = ""
    escape = False

    for ch in code:
        if in_string:
            tokens.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_quote:
                in_string = False
                string_quote = ""
            continue

        if ch in {"'", '"'}:
            in_string = True
            string_quote = ch
            tokens.append(ch)
            continue

        if ch == "{":
            tokens.append(" {\n")
            continue
        if ch == "}":
            tokens.append("\n}\n")
            continue
        if ch == ";":
            tokens.append(";\n")
            continue

        tokens.append(ch)

    rough = "".join(tokens)
    lines = [ln.strip() for ln in rough.splitlines() if ln.strip()]
    if not lines:
        return code

    formatted = []
    indent = 0

    for line in lines:
        if line.startswith("}"):
            indent = max(indent - 1, 0)

        formatted.append(("    " * indent) + line)

        if line.endswith("{"):
            indent += 1

    return "\n".join(formatted)


def build_prompt(code: str, source_lang: str, target_lang: str) -> str:
    pair_hint = LANG_HINTS.get((source_lang, target_lang), "Preserve the same behavior using simple target-language syntax.")
    return f"""{MASTER_PROMPT.replace('SOURCE_LANGUAGE', source_lang).replace('TARGET_LANGUAGE', target_lang)}

Extra conversion hint:
{pair_hint}

Source language: {source_lang}
Target language: {target_lang}

Input code:
{code}

Return only {target_lang} code.
"""


def get_openrouter_model() -> str:
    return (os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()


def get_openrouter_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY not found in backend/.env. Add OPENROUTER_API_KEY=your_key_here",
        )

    # OpenRouter supports the OpenAI SDK when base_url points to OpenRouter.
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        timeout=AI_TIMEOUT_SECONDS,
    )


def call_openrouter(prompt: str, client: OpenAI, model: str) -> str:
    try:
        result = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=1200,
            extra_headers={
                # Optional but recommended by OpenRouter for app identification.
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "CodeConverter Demo"),
            },
            messages=[
                {"role": "system", "content": "Return only converted source code. No markdown. No explanation."},
                {"role": "user", "content": prompt},
            ],
        )
        text = (result.choices[0].message.content or "").strip() if result.choices else ""
        if not text:
            raise HTTPException(status_code=502, detail="OpenRouter returned empty output.")
        return text
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenRouter request failed: {exc}") from exc


CODET5_ENGINE = None
LANGUAGE_DETECTOR = None


def get_codet5_engine() -> CodeT5InferenceEngine:
    global CODET5_ENGINE
    if CODET5_ENGINE is None:
        CODET5_ENGINE = CodeT5InferenceEngine()
    return CODET5_ENGINE


def get_language_detector() -> MLLanguageDetector:
    global LANGUAGE_DETECTOR
    if LANGUAGE_DETECTOR is None:
        LANGUAGE_DETECTOR = MLLanguageDetector()
    return LANGUAGE_DETECTOR


def convert_pipeline(code: str, source_lang: str, target_lang: str) -> ConvertResponse:
    cleaned_input = preprocess(code)
    if not cleaned_input:
        raise HTTPException(status_code=400, detail="Input code is empty after preprocessing.")

    inferred_lang = detect_language_from_code(cleaned_input)
    # Soft block reconversion: if input already looks like target language,
    # skip remote model call and return existing content with a warning.
    if inferred_lang == target_lang and inferred_lang != source_lang:
        return ConvertResponse(
            converted_code=cleaned_input,
            model="soft-block",
            warning=f"Input already appears to be {target_lang}. Skipped reconversion.",
            iterations=0,
            semantic_score=100,
            execution_output="Skipped execution (input already in target language).",
            execution_error=None,
            status="success",
        )

    rule_input = rule_based_preconvert(cleaned_input, source_lang, target_lang)
    if not rule_input:
        rule_input = cleaned_input

    warning = None
    model = "codet5"
    mode = "ast-codet5-judge0"

    # Semantic-aware pre-parse before translation.
    _ = ast_feature_dict(rule_input, source_lang)

    try:
        codet5_engine = get_codet5_engine()
        codet5_out = codet5_engine.translate(rule_input, source_lang, target_lang)
        converted = codet5_out.converted_code
        model = codet5_out.used_model or "codet5"
    except Exception:
        # Keep OpenRouter fallback for resiliency if local/inference path fails.
        model = get_openrouter_model()
        client = get_openrouter_client()
        prompt = build_prompt(rule_input, source_lang, target_lang)
        raw_output = call_openrouter(prompt, client, model)
        converted = clean_ai_output(raw_output, target_lang)
        mode = "ast-openrouter-fallback-judge0"
        warning = "CodeT5 inference failed. Used OpenRouter fallback."

    converted = sanitize_target_output(
        converted,
        target_lang,
        source_lang=source_lang,
        source_code=cleaned_input,
    )
    if not converted:
        raise HTTPException(status_code=502, detail="Conversion produced empty output.")

    val_warnings = collect_post_conversion_warnings(converted, target_lang)
    if val_warnings:
        val_msg = format_validation_warnings(val_warnings)
        warning = f"{warning}; {val_msg}" if warning else val_msg
    strict = (os.getenv("CONVERT_STRICT_VALIDATE") or "").strip().lower() in ("1", "true", "yes")
    if strict and val_warnings:
        critical = [w for w in val_warnings if any(x in w.lower() for x in ("syntax", "invalid", "empty"))]
        if critical:
            raise HTTPException(status_code=502, detail=format_validation_warnings(critical))

    sem = semantic_similarity_score(cleaned_input, source_lang, converted, target_lang)

    try:
        run_res = run_code(converted, target_lang)
        execution_output = run_res.output
        execution_error = run_res.error
    except HTTPException as exc:
        execution_output = f"Execution validation unavailable: {exc.detail}"
        execution_error = str(exc.detail)

    if model == "openrouter/free":
        warning = (
            "Using openrouter/free. Output quality can vary because OpenRouter may route to different free models."
            if not warning
            else warning
        )

    response_status = "success" if not execution_error else "warning"
    if val_warnings and response_status == "success":
        blob = " ".join(val_warnings).lower()
        if any(k in blob for k in ("syntax", "invalid", "unbalanced", "empty")):
            response_status = "warning"

    return ConvertResponse(
        converted_code=converted,
        provider="codet5" if "codet5" in model.lower() else "openrouter",
        model=model,
        mode=mode,
        warning=warning,
        iterations=1,
        semantic_score=sem["semantic_score"],
        execution_output=execution_output,
        execution_error=execution_error,
        status=response_status,
    )


# ============================================================
# Remote code execution via Judge0 (no local compilers).
# ============================================================

JUDGE0_TIMEOUT_USER_MESSAGE = (
    "Code execution service is taking too long. Please try again."
)
JUDGE0_UNREACHABLE_USER_MESSAGE = (
    "Unable to reach the code execution service. Please try again later."
)


def _judge0_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = (os.getenv("JUDGE0_API_KEY") or "").strip()
    api_host = (os.getenv("JUDGE0_API_HOST") or "").strip()

    if api_key:
        headers["X-RapidAPI-Key"] = api_key
    if api_host:
        headers["X-RapidAPI-Host"] = api_host

    return headers


def _judge0_http_request(method: str, url: str, **request_kwargs) -> Tuple[Optional[requests.Response], Optional[str]]:
    """
    Call Judge0 with retries. Returns (response, None) on success, or (None, user_message) after failures.

    Retries up to 3 times with 2 seconds between attempts on timeout or connection errors.
    Uses a 60-second HTTP read/connect timeout per attempt by default.
    """
    http_timeout = float(os.getenv("JUDGE0_HTTP_TIMEOUT_SECONDS", "60"))
    max_retries = int(os.getenv("JUDGE0_MAX_RETRIES", "3"))
    retry_delay = float(os.getenv("JUDGE0_RETRY_DELAY_SECONDS", "2"))

    if "headers" not in request_kwargs:
        request_kwargs["headers"] = _judge0_headers()
    request_kwargs["timeout"] = http_timeout

    last_error: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        try:
            if method.upper() == "GET":
                response = requests.get(url, **request_kwargs)
            else:
                response = requests.post(url, **request_kwargs)
            return response, None
        except requests.Timeout as exc:
            last_error = exc
            logger.warning(
                "Judge0 %s timeout (attempt %s/%s) url=%s timeout=%ss detail=%r",
                method.upper(),
                attempt,
                max_retries,
                url,
                http_timeout,
                exc,
                exc_info=True,
            )
        except requests.RequestException as exc:
            last_error = exc
            logger.error(
                "Judge0 %s request error (attempt %s/%s) url=%s detail=%r",
                method.upper(),
                attempt,
                max_retries,
                url,
                exc,
                exc_info=True,
            )

        if attempt < max_retries:
            time.sleep(retry_delay)

    if isinstance(last_error, requests.Timeout):
        logger.error(
            "Judge0 gave up after %s attempts (timeout). url=%s last_error=%r",
            max_retries,
            url,
            last_error,
            exc_info=True,
        )
        return None, JUDGE0_TIMEOUT_USER_MESSAGE

    logger.error(
        "Judge0 gave up after %s attempts (not a timeout). url=%s last_error=%r",
        max_retries,
        url,
        last_error,
        exc_info=True,
    )
    return None, JUDGE0_UNREACHABLE_USER_MESSAGE


def run_code(code: str, language: str) -> RunResponse:
    """
    Submit code to Judge0 and poll for results.
    Does not raise for Judge0 network failures; returns RunResponse with a user-facing message instead.
    """
    judge0_base = (os.getenv("JUDGE0_BASE_URL") or "https://ce.judge0.com").strip().rstrip("/")
    language_id = JUDGE0_LANGUAGE_IDS.get(language)
    if not language_id:
        raise HTTPException(status_code=400, detail=f"Execution unsupported for language '{language}'.")

    submit_url = f"{judge0_base}/submissions?base64_encoded=false&wait=false"
    poll_timeout = float(os.getenv("JUDGE0_POLL_TIMEOUT_SECONDS", "120"))
    poll_interval = float(os.getenv("JUDGE0_POLL_INTERVAL_SECONDS", "1"))
    timeout_at = time.time() + poll_timeout

    source = prepare_java_for_judge0(code) if language == "java" else code

    try:
        submit_res, err_msg = _judge0_http_request(
            "POST",
            submit_url,
            json={"source_code": source, "language_id": language_id},
        )
        if err_msg:
            return RunResponse(output=err_msg, error=err_msg)

        try:
            submit_res.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(
                "Judge0 submit HTTP error status=%s body=%s",
                submit_res.status_code,
                submit_res.text[:500] if submit_res.text else "",
                exc_info=True,
            )
            friendly = "Code execution service returned an error. Please try again."
            return RunResponse(output=friendly, error=str(exc))

        token = submit_res.json().get("token")
        if not token:
            logger.error("Judge0 submit response missing token: %s", submit_res.text[:500])
            return RunResponse(
                output="Code execution service did not accept the submission. Please try again.",
                error="Missing submission token",
            )

        result_url = f"{judge0_base}/submissions/{token}?base64_encoded=false&fields=stdout,stderr,compile_output,status"

        while time.time() < timeout_at:
            result_res, poll_err = _judge0_http_request("GET", result_url)
            if poll_err:
                return RunResponse(output=poll_err, error=poll_err)

            try:
                result_res.raise_for_status()
            except requests.HTTPError as exc:
                logger.error(
                    "Judge0 poll HTTP error status=%s body=%s",
                    result_res.status_code,
                    result_res.text[:500] if result_res.text else "",
                    exc_info=True,
                )
                friendly = "Code execution service returned an error while fetching results. Please try again."
                return RunResponse(output=friendly, error=str(exc))

            try:
                result = result_res.json()
            except ValueError as exc:
                logger.error("Judge0 poll invalid JSON: %s", result_res.text[:500], exc_info=True)
                return RunResponse(
                    output="Code execution service returned an invalid response. Please try again.",
                    error=str(exc),
                )

            status_id = (result.get("status") or {}).get("id", 0)

            if status_id not in {1, 2}:  # In Queue, Processing
                compile_output = (result.get("compile_output") or "").strip()
                stderr = (result.get("stderr") or "").strip()
                stdout = (result.get("stdout") or "").strip()

                if compile_output:
                    return RunResponse(output=compile_output, error=compile_output)
                if stderr:
                    return RunResponse(output=stderr, error=stderr)
                if stdout:
                    return RunResponse(output=stdout, error=None)
                return RunResponse(output="No Output", error=None)

            time.sleep(poll_interval)

        logger.warning(
            "Judge0 poll window exceeded (%.0fs) without terminal status for token=%s",
            poll_timeout,
            token,
        )
        return RunResponse(
            output=JUDGE0_TIMEOUT_USER_MESSAGE,
            error=JUDGE0_TIMEOUT_USER_MESSAGE,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error in run_code: %s", exc)
        return RunResponse(
            output="An unexpected error occurred while contacting the code execution service.",
            error=str(exc),
        )


app = FastAPI(title="Multi-Language Code Converter API - OpenRouter Build")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "provider": "openrouter", "model": get_openrouter_model()}


@app.post("/convert", response_model=ConvertResponse)
def convert(payload: ConvertRequest) -> ConvertResponse:
    inferred = detect_language(payload.filename)
    src = payload.source_lang if payload.source_lang else inferred
    if src == "unknown":
        raise HTTPException(status_code=400, detail="Could not auto-detect source language. Provide source_lang.")

    source_lang = normalize_language(src)
    target_lang = normalize_language(payload.target_lang)

    if source_lang == target_lang:
        raise HTTPException(status_code=400, detail="source_lang and target_lang must be different.")

    return convert_pipeline(payload.code, source_lang, target_lang)


@app.post("/compile", response_model=CompileResponse)
def compile_endpoint(payload: CompileRequest) -> CompileResponse:
    return CompileResponse(success=False, output="Compile endpoint deprecated. Use /run for Judge0 execution.")


@app.post("/run", response_model=RunResponse)
def run_endpoint(payload: RunRequest) -> RunResponse:
    language = normalize_language(payload.language)
    return run_code(payload.code, language)


@app.post("/detect-language", response_model=DetectLanguageResponse)
def detect_language_endpoint(payload: DetectLanguageRequest) -> DetectLanguageResponse:
    code = preprocess(payload.code)
    heuristic = detect_language_from_code(code)
    detector = get_language_detector()
    ml = detector.predict(code)
    ml_lang = ml.get("language", "unknown")
    confidence = float(ml.get("confidence", 0.0))

    if confidence < 0.55 and heuristic in SUPPORTED_LANGUAGES:
        return DetectLanguageResponse(language=heuristic, confidence=max(confidence, 0.55), method="hybrid")

    if ml_lang not in SUPPORTED_LANGUAGES and heuristic in SUPPORTED_LANGUAGES:
        return DetectLanguageResponse(language=heuristic, confidence=max(confidence, 0.51), method="hybrid")

    return DetectLanguageResponse(language=ml_lang, confidence=confidence, method="ml")
