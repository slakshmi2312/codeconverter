import { useMemo, useState } from "react";
import { ArrowLeftRight, Download, FolderOpen, Loader2, Sparkles, Wrench } from "lucide-react";
import CodeEditorPanel from "./components/CodeEditorPanel";
import { compileCode, convertCode } from "./services/api";

const languages = [
  { value: "python", label: "Python" },
  { value: "java", label: "Java" },
  { value: "c", label: "C" },
  { value: "javascript", label: "JavaScript" },
];

const extensionMap = {
  python: "py",
  java: "java",
  c: "c",
  javascript: "js",
};

const extensionToLanguage = {
  py: "python",
  java: "java",
  c: "c",
  h: "c",
  js: "javascript",
  jsx: "javascript",
};

function detectLanguageFromContent(content) {
  if (/System\.out\.println|public static void main|class\s+\w+/.test(content)) return "java";
  if (/#include|printf\(|scanf\(|\bmalloc\(/.test(content)) return "c";
  if (/def\s+\w+\(|if __name__ == "__main__"|print\(/.test(content)) return "python";
  if (/function\s+\w+|console\.log|=>/.test(content)) return "javascript";
  return "python";
}

function App() {
  const [sourceLang, setSourceLang] = useState("python");
  const [targetLang, setTargetLang] = useState("java");
  const [inputCode, setInputCode] = useState("");
  const [outputCode, setOutputCode] = useState("");
  const [compileOutput, setCompileOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copiedSource, setCopiedSource] = useState(false);
  const [copiedTarget, setCopiedTarget] = useState(false);

  const canConvert = useMemo(
    () => inputCode.trim() && sourceLang !== targetLang && !loading,
    [inputCode, sourceLang, targetLang, loading]
  );

  const handleSwap = () => {
    const prev = sourceLang;
    setSourceLang(targetLang);
    setTargetLang(prev);
  };

  const handleConvert = async () => {
    if (!canConvert) return;
    setLoading(true);
    setError("");
    try {
      const res = await convertCode({
        code: inputCode,
        source_lang: sourceLang,
        target_lang: targetLang,
      });
      setOutputCode(res.converted_code || "");
      setCompileOutput("");
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Conversion failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!outputCode.trim()) return;
    const ext = extensionMap[targetLang] || "txt";
    const blob = new Blob([outputCode], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `converted.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopySource = async () => {
    if (!inputCode.trim()) return;
    await navigator.clipboard.writeText(inputCode);
    setCopiedSource(true);
    setTimeout(() => setCopiedSource(false), 1400);
  };

  const handleCopyTarget = async () => {
    if (!outputCode.trim()) return;
    await navigator.clipboard.writeText(outputCode);
    setCopiedTarget(true);
    setTimeout(() => setCopiedTarget(false), 1400);
  };

  const handleCompile = async () => {
    const codeToCompile = outputCode.trim() ? outputCode : inputCode;
    if (!codeToCompile.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await compileCode({
        code: codeToCompile,
        language: outputCode.trim() ? targetLang : sourceLang,
      });
      setCompileOutput(`${res.success ? "SUCCESS" : "FAILED"}: ${res.output}`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Compile failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleCompileSource = async () => {
    if (!inputCode.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await compileCode({ code: inputCode, language: sourceLang });
      setCompileOutput(`SOURCE ${res.success ? "OK" : "FAILED"}: ${res.output}`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Source compile failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleCompileTarget = async () => {
    if (!outputCode.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await compileCode({ code: outputCode, language: targetLang });
      setCompileOutput(`TARGET ${res.success ? "OK" : "FAILED"}: ${res.output}`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Target compile failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleFolderUpload = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;

    const fileContents = await Promise.all(
      files.map(async (file) => ({
        name: file.webkitRelativePath || file.name,
        text: await file.text(),
      }))
    );

    const languageHits = { python: 0, java: 0, c: 0, javascript: 0 };
    for (const file of files) {
      const ext = file.name.split(".").pop()?.toLowerCase() || "";
      const mapped = extensionToLanguage[ext];
      if (mapped) languageHits[mapped] += 1;
    }

    const merged = fileContents
      .map((entry) => `// File: ${entry.name}\n${entry.text}`)
      .join("\n\n");

    const dominantLang =
      Object.entries(languageHits).sort((a, b) => b[1] - a[1])[0]?.[1] > 0
        ? Object.entries(languageHits).sort((a, b) => b[1] - a[1])[0][0]
        : detectLanguageFromContent(merged);

    setInputCode(merged);
    setSourceLang(dominantLang);
    setError("");
  };

  return (
    <main className="min-h-screen w-full p-3 text-slate-800 md:p-4">
      <section className="h-[calc(100vh-1.5rem)] rounded-3xl border border-slate-200 bg-white/85 p-4 shadow-[0_20px_80px_rgba(148,163,184,0.3)] md:p-5">
        <header className="mb-5">
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
            Multi-Language <span className="text-violet-600">Code Converter</span>
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Hybrid transpilation with rule-based hints + Gemini 1.5 Flash.
          </p>
        </header>

        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
          <select
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
            value={sourceLang}
            onChange={(e) => setSourceLang(e.target.value)}
            disabled={loading}
          >
            {languages.map((lang) => (
              <option key={lang.value} value={lang.value}>
                {lang.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-violet-300 bg-violet-50 text-violet-600 hover:bg-violet-100"
            onClick={handleSwap}
            disabled={loading}
          >
            <ArrowLeftRight className="h-4 w-4" />
          </button>

          <select
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            disabled={loading}
          >
            {languages.map((lang) => (
              <option key={lang.value} value={lang.value}>
                {lang.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="ml-auto inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            onClick={handleConvert}
            disabled={!canConvert}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Convert
          </button>

          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm hover:border-cyan-400"
            onClick={handleDownload}
          >
            <Download className="h-4 w-4" />
            Download
          </button>

          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm hover:border-cyan-400"
            onClick={handleCompile}
            disabled={loading}
          >
            <Wrench className="h-4 w-4" />
            Compile
          </button>

          <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm hover:border-cyan-400">
            <FolderOpen className="h-4 w-4" />
            Upload Folder
            <input
              type="file"
              className="hidden"
              multiple
              webkitdirectory=""
              directory=""
              onChange={handleFolderUpload}
            />
          </label>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {compileOutput ? (
          <div className="mb-4 rounded-xl border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {compileOutput}
          </div>
        ) : null}

        <section className="grid h-[calc(100%-210px)] gap-4 xl:grid-cols-2">
          <CodeEditorPanel
            title="Source Code"
            language={sourceLang}
            value={inputCode}
            onChange={setInputCode}
            onCopy={handleCopySource}
            copied={copiedSource}
            onCompile={handleCompileSource}
            height="100%"
          />
          <CodeEditorPanel
            title="Converted Code"
            language={targetLang}
            value={outputCode}
            onChange={setOutputCode}
            onCopy={handleCopyTarget}
            copied={copiedTarget}
            onCompile={handleCompileTarget}
            height="100%"
          />
        </section>
      </section>
    </main>
  );
}

export default App;
