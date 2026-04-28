import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import generativeai as genai
from pydantic import BaseModel, Field
from tree_sitter_languages import get_parser

load_dotenv()

MASTER_PROMPT = """You are a compiler-level multi-language transpiler.

Convert code from SOURCE_LANGUAGE to TARGET_LANGUAGE.

Supported languages:
- C
- Java
- Python
- JavaScript

========================
CORE RULES
========================

1. Perform STRUCTURAL + SEMANTIC conversion (NOT text replacement)

2. Remove ALL source-language artifacts:
   - C/Java: types, pointers, semicolons, headers
   - Python: indentation-based blocks -> braces (if needed)
   - JavaScript: adapt dynamic typing carefully

3. Apply TARGET language rules strictly:
   - Correct syntax
   - Correct structure
   - Idiomatic usage

4. Handle these constructs correctly:
   - functions
   - loops (for, while)
   - conditionals
   - recursion
   - arrays / lists
   - basic input/output
   - variable scope

5. SEMANTIC TRANSFORMATION (CRITICAL):
   - pointers -> references/returns
   - memory logic -> native constructs
   - swap logic -> tuple/return
   - class -> equivalent structure

6. OUTPUT RULES:
   - Only TARGET language code
   - No mixing languages
   - No explanation
   - Must compile/run correctly

========================
SELF-VALIDATION
========================

Before returning:
- Check syntax correctness
- Ensure code compiles logically
- Fix all errors internally

If invalid -> FIX before output
"""

EXTENSION_MAP = {
    ".c": "c",
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
}

SUPPORTED_LANGUAGES = {"python", "java", "c", "javascript"}
GEMINI_MODELS = ["gemini-1.5-flash-latest", "gemini-1.5-flash-8b-latest", "gemini-2.0-flash"]
MAX_MODEL_RETRIES = 2
AI_TIMEOUT_SECONDS = 18
PIPELINE_MAX_FIX_LOOPS = 3

LANG_HINTS: Dict[Tuple[str, str], str] = {
    ("c", "python"): "Handle pointers, malloc/free patterns, and null checks using idiomatic Python objects and None.",
    ("java", "javascript"): "Preserve class behavior. If cleaner, convert to idiomatic JavaScript classes or functional modules.",
    ("python", "java"): "Map dynamic typing to safe Java types where obvious and keep control flow intact.",
    ("javascript", "python"): "Convert async/promises into clean synchronous or async Python syntax as appropriate.",
}


class ConvertRequest(BaseModel):
    code: str = Field(min_length=1)
    source_lang: Optional[str] = None
    target_lang: str
    filename: Optional[str] = None


class ConvertResponse(BaseModel):
    converted_code: str
    provider: str = "gemini-1.5-flash"
    mode: str = "hybrid"
    warning: Optional[str] = None
    source_output: Optional[str] = None
    target_output: Optional[str] = None
    iterations: int = 1


class CompileRequest(BaseModel):
    code: str = Field(min_length=1)
    language: str


class CompileResponse(BaseModel):
    success: bool
    output: str


def detect_language(filename: Optional[str]) -> str:
    if not filename:
        return "unknown"
    lowered = filename.lower()
    for ext, lang in EXTENSION_MAP.items():
        if lowered.endswith(ext):
            return lang
    return "unknown"


def normalize_language(lang: Optional[str]) -> str:
    value = (lang or "").strip().lower()
    aliases = {"py": "python", "js": "javascript"}
    value = aliases.get(value, value)
    if value not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{lang}'. Supported: python, java, c, javascript.",
        )
    return value


def preprocess(code: str) -> str:
    code = re.sub(r"#include\s*<[^>]+>\s*", "", code)
    code = re.sub(r"^\s*import\s+.*?;\s*$", "", code, flags=re.MULTILINE)
    code = re.sub(r"^\s*using\s+namespace\s+\w+\s*;\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def get_model_candidates() -> list[str]:
    configured = (os.getenv("GEMINI_MODEL") or "").strip()
    candidates = [configured, *GEMINI_MODELS] if configured else GEMINI_MODELS
    unique: list[str] = []
    seen = set()
    for model in candidates:
        if model and model not in seen:
            unique.append(model)
            seen.add(model)
    return unique


def compile_code(language: str, code: str) -> CompileResponse:
    with tempfile.TemporaryDirectory() as tmp:
        if language == "python":
            try:
                compile(code, "<string>", "exec")
                return CompileResponse(success=True, output="Python syntax check passed.")
            except SyntaxError as exc:
                return CompileResponse(success=False, output=f"Python syntax error: {exc}")

        if language == "javascript":
            source = os.path.join(tmp, "main.js")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)
            proc = subprocess.run(["node", "--check", source], capture_output=True, text=True, shell=False)
            return CompileResponse(success=proc.returncode == 0, output=(proc.stderr or proc.stdout or "JavaScript syntax check passed.").strip())

        if language == "c":
            source = os.path.join(tmp, "main.c")
            out_exe = os.path.join(tmp, "main.exe" if os.name == "nt" else "main")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)
            proc = subprocess.run(["gcc", source, "-o", out_exe], capture_output=True, text=True, shell=False)
            return CompileResponse(success=proc.returncode == 0, output=(proc.stderr or proc.stdout or "C compile check passed.").strip())

        if language == "java":
            source = os.path.join(tmp, "Main.java")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)
            proc = subprocess.run(["javac", source], capture_output=True, text=True, shell=False)
            return CompileResponse(success=proc.returncode == 0, output=(proc.stderr or proc.stdout or "Java compile check passed.").strip())

    return CompileResponse(success=False, output="Unsupported language for compilation.")


def run_code(language: str, code: str) -> Optional[str]:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if language == "python":
                result = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    return None
                return result.stdout.strip()

            if language == "javascript":
                result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    return None
                return result.stdout.strip()

            if language == "c":
                source = os.path.join(tmp, "temp.c")
                out_exe = os.path.join(tmp, "temp.exe" if os.name == "nt" else "temp")
                with open(source, "w", encoding="utf-8") as fh:
                    fh.write(code)
                build = subprocess.run(["gcc", source, "-o", out_exe], capture_output=True, text=True, timeout=10)
                if build.returncode != 0:
                    return None
                run = subprocess.run([out_exe], capture_output=True, text=True, timeout=10)
                if run.returncode != 0:
                    return None
                return run.stdout.strip()

            if language == "java":
                source = os.path.join(tmp, "Main.java")
                with open(source, "w", encoding="utf-8") as fh:
                    fh.write(code)
                build = subprocess.run(["javac", source], capture_output=True, text=True, timeout=10)
                if build.returncode != 0:
                    return None
                run = subprocess.run(["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=10)
                if run.returncode != 0:
                    return None
                return run.stdout.strip()
    except Exception:
        return None
    return None


def outputs_match(src_out: Optional[str], tgt_out: Optional[str]) -> bool:
    if src_out is None or tgt_out is None:
        return False
    return src_out.strip() == tgt_out.strip()


def validate_with_tree_sitter(code: str, language: str, stage: str) -> None:
    try:
        parser = get_parser(language)
        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node
        if root.has_error:
            raise HTTPException(
                status_code=400 if stage == "source" else 502,
                detail=f"{stage.capitalize()} AST validation failed for {language}: syntax errors detected.",
            )
    except HTTPException:
        raise
    except Exception:
        compile_result = compile_code(language, code)
        if not compile_result.success:
            raise HTTPException(
                status_code=400 if stage == "source" else 502,
                detail=f"{stage.capitalize()} syntax validation failed for {language}: {compile_result.output}",
            )


def detect_boilerplate(source: str, source_lang: str) -> str:
    hints = []
    if source_lang == "c":
        if "#include" in source:
            hints.append("C headers detected. Keep required imports/includes in target equivalent.")
        if "int main(" in source:
            hints.append("Main entrypoint detected. Preserve entrypoint behavior.")
    if source_lang == "java":
        if "public static void main" in source:
            hints.append("Java main class detected. Preserve startup flow.")
        if "class " in source:
            hints.append("Java class structure detected. Preserve class-level behavior.")
    if source_lang == "python":
        if "if __name__ == \"__main__\"" in source:
            hints.append("Python main guard detected. Preserve executable entry behavior.")
    if source_lang == "javascript":
        if "module.exports" in source or "export default" in source:
            hints.append("Module export pattern detected. Preserve module interface.")
    return "\n".join(hints)


def translation_hint(source_lang: str, target_lang: str) -> str:
    return LANG_HINTS.get((source_lang, target_lang), "Preserve exact runtime logic and output behavior.")


def clean_ai_output(text: str, target_lang: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    lines = cleaned.splitlines()
    while lines and lines[0].strip().lower().startswith(("here", "sure", "converted")):
        lines.pop(0)
    cleaned = "\n".join(lines).strip()
    if target_lang == "python":
        cleaned = re.sub(r";+\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned


def sanitize_target_output(code: str, target_lang: str) -> str:
    out = code.strip()
    if target_lang == "python":
        out = re.sub(r"^\s*(int|float|double|long|char|String|boolean)\s+(\w+)\s*=", r"\2 =", out, flags=re.MULTILINE)
        out = out.replace("{", "").replace("}", "")
        out = out.replace("&", "")
        out = re.sub(r"\*(\w+)", r"\1", out)
        out = out.replace("System.out.println", "print")
        out = re.sub(r"console\.log\((.+?)\)", r"print(\1)", out)
        out = re.sub(r'printf\(".*?",\s*(.+?)\)', r"print(\1)", out)
        out = re.sub(r";+\s*$", "", out, flags=re.MULTILINE)
    elif target_lang == "java":
        out = out.replace("print(", "System.out.println(")
        out = re.sub(r'printf\(".*?",\s*(.+?)\);?', r"System.out.println(\1);", out)
        if "public class " not in out:
            out = f"public class Main {{\n{out}\n}}"
    elif target_lang == "c":
        out = out.replace("System.out.println(", 'printf("%s\\n", ')
        out = out.replace("console.log(", 'printf("%s\\n", ')
        if "#include <stdio.h>" not in out:
            out = "#include <stdio.h>\n\n" + out
    elif target_lang == "javascript":
        out = out.replace("System.out.println(", "console.log(")
        out = re.sub(r'printf\(".*?",\s*(.+?)\);?', r"console.log(\1);", out)
    return out.strip()


def build_prompt(code: str, source_lang: str, target_lang: str) -> str:
    boilerplate_notes = detect_boilerplate(code, source_lang)
    pair_hint = translation_hint(source_lang, target_lang)
    return (
        MASTER_PROMPT.replace("SOURCE_LANGUAGE", source_lang).replace("TARGET_LANGUAGE", target_lang)
        + "\n\n"
        + f"Rule hints:\n{pair_hint}\n{boilerplate_notes if boilerplate_notes else 'No special boilerplate detected.'}\n\n"
        + "INPUT:\n"
        + code
        + "\n\nOUTPUT:\n<TARGET_CODE_ONLY>"
    )


def call_gemini_with_fallback(prompt: str) -> str:
    last_error = None
    for model_name in get_model_candidates():
        for attempt in range(MAX_MODEL_RETRIES):
            try:
                model = genai.GenerativeModel(model_name)
                result = model.generate_content(prompt, generation_config={"temperature": 0})
                text = result.text if hasattr(result, "text") else ""
                if text and text.strip():
                    return text
            except Exception as exc:
                last_error = exc
                if attempt < MAX_MODEL_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
    raise HTTPException(status_code=502, detail=f"Gemini request failed: {last_error}")


def call_gemini_with_timeout(prompt: str) -> str:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call_gemini_with_fallback, prompt)
        try:
            return future.result(timeout=AI_TIMEOUT_SECONDS)
        except FuturesTimeoutError as exc:
            raise HTTPException(status_code=504, detail=f"AI conversion timed out after {AI_TIMEOUT_SECONDS}s.") from exc


def convert_with_ai(code: str, source_lang: str, target_lang: str) -> str:
    prompt = build_prompt(code, source_lang, target_lang)
    raw = call_gemini_with_timeout(prompt)
    cleaned = clean_ai_output(raw, target_lang)
    return sanitize_target_output(cleaned, target_lang)


def convert_pipeline(code: str, source_lang: str, target_lang: str) -> ConvertResponse:
    preprocessed = preprocess(code)
    source_output = run_code(source_lang, preprocessed)

    last_converted = ""
    last_target_output: Optional[str] = None
    warning: Optional[str] = None

    prompt_input = preprocessed
    loops = 0

    for loops in range(1, PIPELINE_MAX_FIX_LOOPS + 1):
        converted = convert_with_ai(prompt_input, source_lang, target_lang)
        last_converted = converted

        if not converted.strip():
            warning = "Model returned empty output."
            continue

        if target_lang in SUPPORTED_LANGUAGES:
            try:
                validate_with_tree_sitter(converted, target_lang, stage="target")
            except HTTPException:
                # keep trying through auto-fix loop
                pass

        target_output = run_code(target_lang, converted)
        last_target_output = target_output

        # If either side cannot run, return best converted code with warning.
        if source_output is None or target_output is None:
            warning = "Could not execute one side for semantic comparison; returning best converted output."
            return ConvertResponse(
                converted_code=converted,
                warning=warning,
                source_output=source_output,
                target_output=target_output,
                iterations=loops,
            )

        if outputs_match(source_output, target_output):
            return ConvertResponse(
                converted_code=converted,
                source_output=source_output,
                target_output=target_output,
                iterations=loops,
            )

        prompt_input = f"""Original Code:
{preprocessed}

Converted Code:
{converted}

Fix mismatch in output.
Source Output: {source_output}
Target Output: {target_output}
"""

    warning = "Output mismatch remained after auto-fix loop; returning best effort."
    return ConvertResponse(
        converted_code=last_converted,
        warning=warning,
        source_output=source_output,
        target_output=last_target_output,
        iterations=loops,
    )


app = FastAPI(title="Multi-Language Code Converter API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


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

    validate_with_tree_sitter(payload.code, source_lang, stage="source")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not found in backend/.env")
    genai.configure(api_key=api_key)

    return convert_pipeline(payload.code, source_lang, target_lang)


@app.post("/compile", response_model=CompileResponse)
def compile_endpoint(payload: CompileRequest) -> CompileResponse:
    language = normalize_language(payload.language)
    return compile_code(language, payload.code)
