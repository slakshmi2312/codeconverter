import Editor from "@monaco-editor/react";

const ICONS = {
  copy: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/copy.svg",
  copied: "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/icons/check2-circle.svg",
};

function CodeEditorPanel({
  title,
  language,
  value,
  onChange,
  onCopy,
  copied = false,
  theme = "light",
  readOnly = false,
  height = "460px",
}) {
  const isDark = theme === "dark";
  const editorTheme = isDark ? "soft-dark" : "light";

  const handleBeforeMount = (monaco) => {
    monaco.editor.defineTheme("soft-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": "#1e293b",
        "editorGutter.background": "#1e293b",
        "editorLineNumber.foreground": "#94a3b8",
        "editorLineNumber.activeForeground": "#e2e8f0",
      },
    });
  };

  return (
    <section
      className={`overflow-hidden rounded-2xl shadow-sm ${
        isDark ? "border border-slate-700 bg-slate-900" : "border border-slate-200 bg-white"
      }`}
    >
      <div className={`flex items-center justify-between px-4 py-2 ${isDark ? "border-b border-slate-700" : "border-b border-slate-200"}`}>
        <h2 className={`text-sm font-semibold ${isDark ? "text-slate-200" : "text-slate-700"}`}>{title}</h2>
        <div className="flex items-center gap-2">
          {onCopy ? (
            <button
              type="button"
              className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs ${
                isDark
                  ? "border border-slate-600 bg-slate-800 text-slate-100 hover:border-cyan-500"
                  : "border border-slate-300 bg-white text-slate-700 hover:border-cyan-400"
              }`}
              onClick={onCopy}
            >
              <img
                src={copied ? ICONS.copied : ICONS.copy}
                alt={copied ? "Copied" : "Copy"}
                className={`h-3.5 w-3.5 ${isDark ? "invert" : ""}`}
              />
              {copied ? "Copied" : "Copy"}
            </button>
          ) : null}
          <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-medium uppercase text-violet-700">
            {language}
          </span>
        </div>
      </div>
      <Editor
        beforeMount={handleBeforeMount}
        height={height}
        language={language}
        value={value}
        onChange={(next) => onChange(next ?? "")}
        theme={editorTheme}
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
