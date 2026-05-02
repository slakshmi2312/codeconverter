import { useMemo, useState } from "react";
import CodeEditorPanel from "./components/CodeEditorPanel";
import { convertCode, runCode } from "./services/api";

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

const ICONS = {
  swap: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/arrow-left-right.svg",
  convert: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/magic.svg",
  loading: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/arrow-repeat.svg",
  download: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/download.svg",
  upload: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/folder2-open.svg",
  run: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/play-fill.svg",
};

function detectLanguageFromContent(content) {
  if (/System\.out\.println|public static void main|class\s+\w+/.test(content)) return "java";
  if (/#include|printf\(|scanf\(|\bmalloc\(/.test(content)) return "c";
  if (/def\s+\w+\(|if __name__ == "__main__"|print\(/.test(content)) return "python";
  if (/function\s+\w+|console\.log|=>/.test(content)) return "javascript";
  return "python";
}

function App() {
  const [theme, setTheme] = useState("light");
  const [sourceLang, setSourceLang] = useState("python");
  const [targetLang, setTargetLang] = useState("java");
  const [inputCode, setInputCode] = useState("");
  const [outputCode, setOutputCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [runningSource, setRunningSource] = useState(false);
  const [runningTarget, setRunningTarget] = useState(false);
  const [error, setError] = useState("");
  const [sourceOutput, setSourceOutput] = useState("");
  const [targetOutput, setTargetOutput] = useState("");
  const [copiedSource, setCopiedSource] = useState(false);
  const [copiedTarget, setCopiedTarget] = useState(false);
  const isDark = theme === "dark";

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

  const handleRunSource = async () => {
    if (!inputCode.trim()) {
      setSourceOutput("No Output");
      return;
    }

    setRunningSource(true);
    try {
      const res = await runCode({ code: inputCode, language: sourceLang });
      setSourceOutput(res.output || "No Output");
    } catch (err) {
      setSourceOutput(err.message || "Run failed.");
    } finally {
      setRunningSource(false);
    }
  };

  const handleRunTarget = async () => {
    if (!outputCode.trim()) {
      setTargetOutput("No Output");
      return;
    }

    setRunningTarget(true);
    try {
      const res = await runCode({ code: outputCode, language: targetLang });
      setTargetOutput(res.output || "No Output");
    } catch (err) {
      setTargetOutput(err.message || "Run failed.");
    } finally {
      setRunningTarget(false);
    }
  };

  return (
    <main className={`min-h-screen w-full p-3 md:p-4 ${isDark ? "bg-slate-900 text-slate-100" : "text-slate-800"}`}>
      <section
        className={`h-[calc(100vh-1.5rem)] rounded-3xl p-4 md:p-5 ${
          isDark
            ? "border border-slate-600 bg-slate-800 shadow-[0_20px_80px_rgba(15,23,42,0.45)]"
            : "border border-slate-200 bg-white/85 shadow-[0_20px_80px_rgba(148,163,184,0.3)]"
        }`}
      >
        <header className="mb-5">
          <h1 className={`text-3xl font-semibold tracking-tight ${isDark ? "text-white" : "text-slate-900"}`}>
            <span className="text-violet-600">Code Converter</span>
          </h1>
        </header>

        <div
          className={`mb-4 flex flex-wrap items-center gap-3 rounded-2xl p-3 ${
            isDark ? "border border-slate-600 bg-slate-700/70" : "border border-slate-200 bg-slate-50/80"
          }`}
        >
          <select
            className={`rounded-xl px-3 py-2 text-sm ${
              isDark ? "border border-slate-500 bg-slate-800 text-slate-100" : "border border-slate-300 bg-white"
            }`}
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
            className={`inline-flex h-9 w-9 items-center justify-center rounded-full ${
              isDark
                ? "border border-violet-500/60 bg-violet-500/20 text-violet-200 hover:bg-violet-500/30"
                : "border border-violet-300 bg-violet-50 text-violet-600 hover:bg-violet-100"
            }`}
            onClick={handleSwap}
            disabled={loading}
          >
            <img src={ICONS.swap} alt="Swap" className={`h-4 w-4 ${isDark ? "invert" : ""}`} />
          </button>

          <select
            className={`rounded-xl px-3 py-2 text-sm ${
              isDark ? "border border-slate-500 bg-slate-800 text-slate-100" : "border border-slate-300 bg-white"
            }`}
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
            <img
              src={loading ? ICONS.loading : ICONS.convert}
              alt={loading ? "Loading" : "Convert"}
              className={`h-4 w-4 ${loading ? "animate-spin" : ""} ${isDark ? "invert" : ""}`}
            />
            Convert
          </button>

          <button
            type="button"
            className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
              isDark
                ? "border border-slate-500 bg-slate-800 text-slate-100 hover:border-cyan-400"
                : "border border-slate-300 bg-white hover:border-cyan-400"
            }`}
            onClick={handleDownload}
          >
            <img src={ICONS.download} alt="Download" className={`h-4 w-4 ${isDark ? "invert" : ""}`} />
            Download
          </button>

          <label
            className={`inline-flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm ${
              isDark
                ? "border border-slate-500 bg-slate-800 text-slate-100 hover:border-cyan-400"
                : "border border-slate-300 bg-white hover:border-cyan-400"
            }`}
          >
            <img src={ICONS.upload} alt="Upload folder" className={`h-4 w-4 ${isDark ? "invert" : ""}`} />
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
          <button
            type="button"
            className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
              isDark
                ? "border border-slate-500 bg-slate-800 text-slate-100 hover:border-cyan-400"
                : "border border-slate-300 bg-white hover:border-cyan-400"
            }`}
            onClick={() => setTheme((prev) => (prev === "light" ? "dark" : "light"))}
          >
            {isDark ? "Light Theme" : "Dark Theme"}
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        <section className="grid h-[calc(100%-210px)] gap-4 xl:grid-cols-2">
          <div className="flex min-h-0 flex-col gap-3">
            <CodeEditorPanel
              title="Source Code"
              language={sourceLang}
              value={inputCode}
              onChange={setInputCode}
              onCopy={handleCopySource}
              copied={copiedSource}
              theme={theme}
              height="100%"
            />
            <button
              type="button"
              className={`inline-flex w-fit items-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60 ${
                isDark
                  ? "border border-slate-500 bg-slate-800 text-slate-100 hover:border-cyan-400"
                  : "border border-slate-300 bg-white hover:border-cyan-400"
              }`}
              onClick={handleRunSource}
              disabled={runningSource}
            >
              <img src={ICONS.run} alt="Run source" className={`h-4 w-4 ${isDark ? "invert" : ""}`} />
              {runningSource ? "Running Source..." : "Run Source"}
            </button>
            <div className={`rounded-xl p-3 text-sm ${isDark ? "border border-slate-600 bg-slate-700" : "border border-slate-200 bg-slate-50"}`}>
              <div className={`mb-2 font-semibold ${isDark ? "text-slate-200" : "text-slate-700"}`}>Source Output:</div>
              <pre className={`max-h-36 overflow-auto whitespace-pre-wrap text-xs ${isDark ? "text-slate-300" : "text-slate-700"}`}>
                {sourceOutput || "No Output"}
              </pre>
            </div>
          </div>
          <div className="flex min-h-0 flex-col gap-3">
            <CodeEditorPanel
              title="Converted Code"
              language={targetLang}
              value={outputCode}
              onChange={setOutputCode}
              onCopy={handleCopyTarget}
              copied={copiedTarget}
              theme={theme}
              height="100%"
            />
            <button
              type="button"
              className={`inline-flex w-fit items-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60 ${
                isDark
                  ? "border border-slate-500 bg-slate-800 text-slate-100 hover:border-cyan-400"
                  : "border border-slate-300 bg-white hover:border-cyan-400"
              }`}
              onClick={handleRunTarget}
              disabled={runningTarget}
            >
              <img src={ICONS.run} alt="Run converted" className={`h-4 w-4 ${isDark ? "invert" : ""}`} />
              {runningTarget ? "Running Converted..." : "Run Converted"}
            </button>
            <div className={`rounded-xl p-3 text-sm ${isDark ? "border border-slate-600 bg-slate-700" : "border border-slate-200 bg-slate-50"}`}>
              <div className={`mb-2 font-semibold ${isDark ? "text-slate-200" : "text-slate-700"}`}>Target Output:</div>
              <pre className={`max-h-36 overflow-auto whitespace-pre-wrap text-xs ${isDark ? "text-slate-300" : "text-slate-700"}`}>
                {targetOutput || "No Output"}
              </pre>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;
