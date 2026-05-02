import os
import re
import time
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field
import requests

load_dotenv()

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
    ("java", "python"): "Convert Java types, braces, main method, and System.out.println into clean Python.",
    ("python", "java"): "Wrap code inside public class Main and public static void main where needed.",
    ("c", "python"): "Convert printf/scanf, loops, arrays, and main function into simple Python.",
    ("python", "c"): "Create a complete C program with #include <stdio.h> and int main where needed.",
    ("javascript", "python"): "Convert console.log, let/const/var, braces, and JS loops into Python.",
    ("python", "javascript"): "Convert print, indentation blocks, and Python lists into JavaScript syntax.",
    ("java", "javascript"): "Convert Java classes and System.out.println into JavaScript classes or simple functions.",
    ("javascript", "java"): "Convert console.log and JS syntax into Java with class Main where needed.",
    ("c", "java"): "Convert C main, printf, primitive variables, and loops into Java class Main.",
    ("java", "c"): "Convert Java main, System.out.println, primitive variables, and loops into C main.",
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


def sanitize_target_output(code: str, target_lang: str) -> str:
    out = code.strip()

    if target_lang == "python":
        out = out.replace("System.out.println", "print")
        out = out.replace("console.log", "print")
        out = re.sub(r"\b(int|float|double|long|String|boolean|char)\s+(\w+)\s*=", r"\2 =", out)
        out = re.sub(r";+\s*$", "", out, flags=re.MULTILINE)

    elif target_lang == "javascript":
        out = out.replace("System.out.println", "console.log")
        out = re.sub(r"^print\((.*)\)$", r"console.log(\1);", out, flags=re.MULTILINE)

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
        )

    rule_input = rule_based_preconvert(cleaned_input, source_lang, target_lang)
    if not rule_input:
        rule_input = cleaned_input

    model = get_openrouter_model()
    client = get_openrouter_client()

    prompt = build_prompt(rule_input, source_lang, target_lang)
    raw_output = call_openrouter(prompt, client, model)
    converted = clean_ai_output(raw_output, target_lang)
    converted = sanitize_target_output(converted, target_lang)

    warning = None
    if model == "openrouter/free":
        warning = "Using openrouter/free. Output quality can vary because OpenRouter may route to different free models."

    return ConvertResponse(
        converted_code=converted,
        model=model,
        warning=warning,
        iterations=1,
    )


# ============================================================
# Remote code execution via Judge0 (no local compilers).
# ============================================================

def _judge0_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = (os.getenv("JUDGE0_API_KEY") or "").strip()
    api_host = (os.getenv("JUDGE0_API_HOST") or "").strip()

    if api_key:
        headers["X-RapidAPI-Key"] = api_key
    if api_host:
        headers["X-RapidAPI-Host"] = api_host

    return headers


def run_code(code: str, language: str) -> RunResponse:
    judge0_base = (os.getenv("JUDGE0_BASE_URL") or "https://ce.judge0.com").strip().rstrip("/")
    language_id = JUDGE0_LANGUAGE_IDS.get(language)
    if not language_id:
        raise HTTPException(status_code=400, detail=f"Execution unsupported for language '{language}'.")

    submit_url = f"{judge0_base}/submissions?base64_encoded=false&wait=false"
    poll_timeout = float(os.getenv("JUDGE0_POLL_TIMEOUT_SECONDS", "12"))
    poll_interval = float(os.getenv("JUDGE0_POLL_INTERVAL_SECONDS", "1"))
    timeout_at = time.time() + poll_timeout

    try:
        submit_res = requests.post(
            submit_url,
            json={"source_code": code, "language_id": language_id},
            headers=_judge0_headers(),
            timeout=15,
        )
        submit_res.raise_for_status()
        token = submit_res.json().get("token")
        if not token:
            raise HTTPException(status_code=502, detail="Judge0 did not return a submission token.")

        result_url = f"{judge0_base}/submissions/{token}?base64_encoded=false&fields=stdout,stderr,compile_output,status"

        while time.time() < timeout_at:
            result_res = requests.get(result_url, headers=_judge0_headers(), timeout=15)
            result_res.raise_for_status()
            result = result_res.json()
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

        return RunResponse(output="Execution timed out while waiting for Judge0 result.", error="Execution timeout")
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Judge0 request failed: {exc}") from exc


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
