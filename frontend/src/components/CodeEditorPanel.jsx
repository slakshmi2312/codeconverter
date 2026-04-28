import Editor from "@monaco-editor/react";
import { CheckCheck, Copy } from "lucide-react";

function CodeEditorPanel({
  title,
  language,
  value,
  onChange,
  onCopy,
  copied = false,
  onCompile,
  readOnly = false,
  height = "460px",
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        <div className="flex items-center gap-2">
          {onCompile ? (
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:border-cyan-400"
              onClick={onCompile}
            >
              Compile
            </button>
          ) : null}
          {onCopy ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:border-cyan-400"
              onClick={onCopy}
            >
              {copied ? <CheckCheck className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
          ) : null}
          <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-medium uppercase text-violet-700">
            {language}
          </span>
        </div>
      </div>
      <Editor
        height={height}
        language={language}
        value={value}
        onChange={(next) => onChange(next ?? "")}
        theme="light"
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 14,
          automaticLayout: true,
          scrollBeyondLastLine: false,
        }}
      />
    </section>
  );
}

export default CodeEditorPanel;
