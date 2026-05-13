import React, { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

const API = process.env.REACT_APP_API_URL || "http://localhost:5000";

async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function apiUpload(path, formData) {
  const res = await fetch(`${API}${path}`, { method: "POST", body: formData });
  return res.json();
}

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  return res.json();
}

const fmtSize = (b) =>
  b < 1024 ? `${b}B` : b < 1048576 ? `${(b / 1024).toFixed(1)}KB` : `${(b / 1048576).toFixed(1)}MB`;

const fmtTime = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Loader() {
  return (
    <div className="loader">
      <span /><span /><span />
    </div>
  );
}

function DocCard({ doc, onRemove }) {
  return (
    <div className="doc-card">
      <div className="doc-icon">
        {doc.status === "ready" ? "📗" : doc.status === "error" ? "❌" : "⏳"}
      </div>
      <div className="doc-info">
        <div className="doc-name" title={doc.name}>{doc.name}</div>
        <div className="doc-meta">
          {doc.size ? fmtSize(doc.size) : ""}{doc.chunks ? ` · ${doc.chunks} chunks` : ""}
        </div>
        <div className="doc-status">
          <span className={`dot ${doc.status === "processing" ? "pulsing" : doc.status === "error" ? "err" : ""}`} />
          <span className="status-label">
            {doc.status === "processing" ? "Indexing…" : doc.status === "error" ? doc.errorMsg || "Failed" : "Indexed ✓"}
          </span>
        </div>
      </div>
      {doc.status !== "processing" && (
        <button className="icon-btn" onClick={() => onRemove(doc.id)} title="Remove">✕</button>
      )}
    </div>
  );
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`msg-row ${isUser ? "user" : "bot"}`}>
      <div className={`avatar ${isUser ? "av-user" : "av-bot"}`}>
        {isUser ? "U" : "G"}
      </div>
      <div className="msg-content">
        <div className={`bubble ${isUser ? "bubble-user" : "bubble-bot"}`}>
          {isUser ? (
            <p>{msg.content}</p>
          ) : (
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          )}
        </div>
        <div className="msg-footer">
          <span className="msg-time">{msg.time}</span>
          {msg.sources?.length > 0 && (
            <div className="sources">
              {msg.sources.map((s) => (
                <span key={s} className="source-chip">📄 {s}</span>
              ))}
            </div>
          )}
          {msg.chunks_used > 0 && (
            <span className="chunk-badge">{msg.chunks_used} chunks retrieved</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [backendOnline, setBackendOnline] = useState(null);
  const bottomRef = useRef(null);
  const textRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const health = await apiGet("/health");
        if (health.status === "ok") {
          setBackendOnline(true);
          const { session_id } = await apiPost("/session", {});
          setSessionId(session_id);
        }
      } catch {
        setBackendOnline(false);
      }
    })();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleUpload = useCallback(
    async (files) => {
      if (!sessionId) return;
      for (const file of files) {
        const ext = "." + file.name.split(".").pop().toLowerCase();
        if (![".pdf", ".txt", ".md"].includes(ext)) {
          alert(`${file.name}: only PDF, TXT, MD supported.`);
          continue;
        }
        const id = Date.now() + Math.random();
        setDocs((p) => [...p, { id, name: file.name, size: file.size, status: "processing" }]);
        setUploading(true);
        const fd = new FormData();
        fd.append("session_id", sessionId);
        fd.append("file", file);
        try {
          const res = await apiUpload("/ingest", fd);
          if (res.success) {
            setDocs((p) =>
              p.map((d) => d.id === id ? { ...d, status: "ready", chunks: res.chunks } : d)
            );
          } else {
            setDocs((p) =>
              p.map((d) => d.id === id ? { ...d, status: "error", errorMsg: res.error } : d)
            );
          }
        } catch {
          setDocs((p) =>
            p.map((d) => d.id === id ? { ...d, status: "error", errorMsg: "Network error" } : d)
          );
        }
        setUploading(false);
      }
    },
    [sessionId]
  );

  const send = async (text) => {
    const q = (text || input).trim();
    if (!q || loading || !sessionId) return;
    setInput("");
    textRef.current && (textRef.current.style.height = "auto");

    const userMsg = { role: "user", content: q, time: fmtTime() };
    setMessages((p) => [...p, userMsg]);
    setLoading(true);

    try {
      const history = messages.slice(-8).map((m) => ({ role: m.role, content: m.content }));
      const res = await apiPost("/chat", { session_id: sessionId, query: q, history });
      setMessages((p) => [
        ...p,
        {
          role: "assistant",
          content: res.answer || res.error || "No response.",
          time: fmtTime(),
          sources: res.sources || [],
          chunks_used: res.chunks_used || 0,
        },
      ]);
    } catch {
      setMessages((p) => [
        ...p,
        { role: "assistant", content: "⚠️ Connection error. Is the backend running?", time: fmtTime() },
      ]);
    }
    setLoading(false);
  };

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const readyDocs = docs.filter((d) => d.status === "ready");
  const totalChunks = readyDocs.reduce((s, d) => s + (d.chunks || 0), 0);

  const starters = [
    "Summarize this document",
    "What are the key points?",
    "List all main topics",
    "What conclusions are drawn?",
    "Explain the methodology used",
  ];

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-left">
          <button className="hamburger" onClick={() => setSidebarOpen((p) => !p)}>☰</button>
          <div className="brand">
            <span className="brand-icon">◈</span>
            <span className="brand-name">DocMind<span className="brand-ai">AI</span></span>
          </div>
        </div>
        <div className="topbar-right">
          <div className={`status-pill ${backendOnline === null ? "status-checking" : backendOnline ? "status-online" : "status-offline"}`}>
            <span className="status-dot" />
            {backendOnline === null ? "Connecting…" : backendOnline ? "Gemini · Online" : "Backend Offline"}
          </div>
        </div>
      </header>

      <div className="body">
        <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
          <div className="sidebar-inner">
            <div className="sidebar-section">
              <div className="section-title">Upload Documents</div>
              <div
                className={`drop-zone ${drag ? "drag-active" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => { e.preventDefault(); setDrag(false); handleUpload([...e.dataTransfer.files]); }}
                onClick={() => fileRef.current?.click()}
              >
                <input ref={fileRef} type="file" accept=".pdf,.txt,.md" multiple style={{ display: "none" }}
                  onChange={(e) => handleUpload([...e.target.files])} />
                <div className="drop-icon">{uploading ? "⏳" : "⬆"}</div>
                <div className="drop-title">{uploading ? "Indexing…" : "Drop files here"}</div>
                <div className="drop-sub">PDF, TXT, MD supported</div>
              </div>
            </div>

            {docs.length > 0 && (
              <div className="sidebar-section">
                <div className="section-title">Documents ({docs.length})</div>
                <div className="doc-list">
                  {docs.map((d) => (
                    <DocCard key={d.id} doc={d}
                      onRemove={(id) => setDocs((p) => p.filter((x) => x.id !== id))} />
                  ))}
                </div>
              </div>
            )}

            {readyDocs.length > 0 && (
              <div className="sidebar-section">
                <div className="section-title">Index Stats</div>
                <div className="stats-grid">
                  <div className="stat-box">
                    <div className="stat-num">{readyDocs.length}</div>
                    <div className="stat-label">Docs Ready</div>
                  </div>
                  <div className="stat-box">
                    <div className="stat-num">{totalChunks}</div>
                    <div className="stat-label">Chunks</div>
                  </div>
                  <div className="stat-box">
                    <div className="stat-num">{messages.filter((m) => m.role === "user").length}</div>
                    <div className="stat-label">Queries</div>
                  </div>
                  <div className="stat-box">
                    <div className="stat-num" style={{ fontSize: "11px", color: "var(--green)" }}>FAISS</div>
                    <div className="stat-label">Vector DB</div>
                  </div>
                </div>
                <button className="clear-all" onClick={() => { setDocs([]); setMessages([]); }}>
                  Clear Everything
                </button>
              </div>
            )}

            <div className="sidebar-section sidebar-footer">
              <div className="tech-stack">
                <span className="tech-tag">Gemini 1.5 Flash</span>
                <span className="tech-tag">FAISS</span>
                <span className="tech-tag">MiniLM</span>
                <span className="tech-tag">Flask</span>
                <span className="tech-tag">React</span>
              </div>
            </div>
          </div>
        </aside>

        <main className="chat">
          <div className="messages-wrap">
            {messages.length === 0 ? (
              <div className="empty">
                <div className="empty-orb">◈</div>
                <h2 className="empty-title">DocMind AI</h2>
                <p className="empty-sub">
                  {backendOnline === false
                    ? "⚠️ Backend not running. Start the Flask server first."
                    : readyDocs.length === 0
                    ? "Upload a PDF or text file on the left to start chatting with your documents."
                    : `${readyDocs.length} document${readyDocs.length > 1 ? "s" : ""} ready. Ask anything:`}
                </p>
                {readyDocs.length > 0 && (
                  <div className="starters">
                    {starters.map((s) => (
                      <button key={s} className="starter" onClick={() => send(s)}>{s}</button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="messages">
                {messages.map((msg, i) => <Message key={i} msg={msg} />)}
                {loading && (
                  <div className="msg-row bot">
                    <div className="avatar av-bot">G</div>
                    <div className="bubble bubble-bot loading-bubble"><Loader /></div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            )}
          </div>

          <div className="input-area">
            <div className="input-box">
              <textarea
                ref={textRef}
                className="input-field"
                rows={1}
                value={input}
                placeholder={readyDocs.length ? "Ask about your documents…" : "Upload a document to get started…"}
                onChange={(e) => {
                  setInput(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px";
                }}
                onKeyDown={onKey}
                disabled={!sessionId || backendOnline === false}
              />
              <button
                className="send-btn"
                onClick={() => send()}
                disabled={loading || !input.trim() || !sessionId}
              >
                ➤
              </button>
            </div>
            <div className="input-hint">Enter to send · Shift+Enter for newline · Powered by Gemini 1.5 Flash + FAISS</div>
          </div>
        </main>
      </div>
    </div>
  );
}