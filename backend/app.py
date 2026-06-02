import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import uuid
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types
from pypdf import PdfReader
import faiss
from sentence_transformers import SentenceTransformer

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
MODEL_ID = "gemini-2.5-flash"
embedder = SentenceTransformer("all-MiniLM-L6-v2")

sessions = {}
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
TOP_K = 5

def extract_text(filepath):
    if filepath.endswith(".pdf"):
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(filepath, "r", errors="ignore") as f:
        return f.read()

def chunk_text(text):
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i:i + CHUNK_SIZE].strip())
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if len(c) > 40]

def build_index(chunks):
    embs = embedder.encode(chunks, show_progress_bar=False)
    embs = np.array(embs, dtype="float32")
    faiss.normalize_L2(embs)
    index = faiss.IndexFlatIP(embs.shape[1])
    index.add(embs)
    return index

def retrieve(query, session_id):
    store = sessions.get(session_id)
    if not store or not store["index"]:
        return []
    q = np.array(embedder.encode([query]), dtype="float32")
    faiss.normalize_L2(q)
    scores, indices = store["index"].search(q, min(TOP_K, len(store["chunks"])))
    return [
        {"text": store["chunks"][i], "source": store["meta"][i]["source"], "score": float(s)}
        for s, i in zip(scores[0], indices[0])
        if i >= 0 and s > 0.1
    ]

@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": MODEL_ID})

@app.route("/session", methods=["POST"])
def create_session():
    sid = str(uuid.uuid4())
    sessions[sid] = {"chunks": [], "index": None, "meta": [], "docs": []}
    return jsonify({"session_id": sid})

@app.route("/ingest", methods=["POST"])
def ingest():
    sid = request.form.get("session_id")
    if not sid or sid not in sessions:
        return jsonify({"error": "Invalid session"}), 400
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file"}), 400
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {".pdf", ".txt", ".md"}:
        return jsonify({"error": "Unsupported file type"}), 400
    filepath = os.path.join(UPLOAD_FOLDER, f"{sid}_{filename}")
    file.save(filepath)
    try:
        text = extract_text(filepath)
        if not text.strip():
            return jsonify({"error": "No text extracted"}), 400
        chunks = chunk_text(text)
        meta = [{"source": filename} for _ in chunks]
        store = sessions[sid]
        store["chunks"].extend(chunks)
        store["meta"].extend(meta)
        store["docs"].append({"name": filename, "chunks": len(chunks)})
        store["index"] = build_index(store["chunks"])
        return jsonify({"success": True, "filename": filename, "chunks": len(chunks)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    sid = data.get("session_id")
    query = data.get("query", "").strip()
    history = data.get("history", [])
    if not sid or sid not in sessions:
        return jsonify({"error": "Invalid session"}), 400
    if not query:
        return jsonify({"error": "Empty query"}), 400
    chunks = retrieve(query, sid)
    if chunks:
        context = "\n\n".join(
            f"[{i+1}] (from {c['source']})\n{c['text']}"
            for i, c in enumerate(chunks)
        )
        system = f"You are a document analyst. Answer ONLY from this context. Cite sources. At the end of your response, always suggest 2-3 relevant follow-up questions the user could ask next to explore the document further, formatted as a bulleted list under the heading '**Follow-up questions:**'.\n\nCONTEXT:\n{context}"
    else:
        system = "You are a helpful assistant. No documents uploaded yet. Ask user to upload one."

    # Build conversation for new SDK
    conversation = []
    for msg in history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        conversation.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    conversation.append(types.Content(role="user", parts=[types.Part(text=f"{system}\n\nQuestion: {query}")]))

    import time
    from google.genai.errors import APIError

    models_to_try = [MODEL_ID, 'gemini-1.5-flash', 'gemini-2.0-flash']
    max_retries = 3

    for model in models_to_try:
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=conversation,
                )
                return jsonify({
                    "answer": response.text,
                    "sources": list({c["source"] for c in chunks}),
                    "chunks_used": len(chunks)
                })
            except APIError as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(2 ** attempt)
                    continue
                else:
                    return jsonify({"error": str(e)}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    return jsonify({"error": "All models are currently experiencing high demand. Please try again in a few minutes."}), 503

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)