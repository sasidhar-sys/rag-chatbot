import os
import time
import uuid

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pypdf import PdfReader

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

client = None

def get_client():
    global client
    if client is None:
        # Use key from environment
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set!")
        client = genai.Client(api_key=api_key)
    return client

MODEL_ID = "gemini-2.5-flash"
EMBED_MODEL = "gemini-embedding-2"

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


def get_embedding(text):
    """Get embedding from Gemini API (runs on Google's cloud, no local RAM needed)."""
    result = get_client().models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type="retrieval_document")
    )
    return np.array(result.embeddings[0].values, dtype="float32")


def get_query_embedding(text):
    """Get query embedding from Gemini API."""
    result = get_client().models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type="retrieval_query")
    )
    return np.array(result.embeddings[0].values, dtype="float32")


def cosine_similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": MODEL_ID})


@app.route("/session", methods=["POST"])
def create_session():
    sid = str(uuid.uuid4())
    sessions[sid] = {"chunks": [], "embeddings": [], "meta": [], "docs": []}
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
        store = sessions[sid]
        new_embeddings = []
        for chunk in chunks:
            emb = get_embedding(chunk)
            new_embeddings.append(emb)
        store["chunks"].extend(chunks)
        store["embeddings"].extend(new_embeddings)
        store["meta"].extend([{"source": filename} for _ in chunks])
        store["docs"].append({"name": filename, "chunks": len(chunks)})
        return jsonify({"success": True, "filename": filename, "chunks": len(chunks)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


def retrieve(query, session_id):
    store = sessions.get(session_id)
    if not store or not store["embeddings"]:
        return []
    q_emb = get_query_embedding(query)
    scored = []
    for i, emb in enumerate(store["embeddings"]):
        score = cosine_similarity(q_emb, emb)
        scored.append((score, i))
    scored.sort(reverse=True)
    top = scored[:TOP_K]
    return [
        {"text": store["chunks"][i], "source": store["meta"][i]["source"], "score": s}
        for s, i in top
        if s > 0.1
    ]


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
        system = (
            f"You are a document analyst. Answer ONLY from this context. Cite sources. "
            f"At the end of your response, always suggest 2-3 relevant follow-up questions the user "
            f"could ask next to explore the document further, formatted as a bulleted list under the heading "
            f"'**Follow-up questions:**'.\n\nCONTEXT:\n{context}"
        )
    else:
        system = "You are a helpful assistant. No documents uploaded yet. Ask user to upload one."

    conversation = []
    for msg in history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        conversation.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    conversation.append(types.Content(role="user", parts=[types.Part(text=f"{system}\n\nQuestion: {query}")]))

    models_to_try = [MODEL_ID, "gemini-1.5-flash", "gemini-2.0-flash"]

    for model in models_to_try:
        for attempt in range(3):
            try:
                response = get_client().models.generate_content(model=model, contents=conversation)
                return jsonify({
                    "answer": response.text,
                    "sources": list({c["source"] for c in chunks}),
                    "chunks_used": len(chunks)
                })
            except APIError as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(2 ** attempt)
                    continue
                return jsonify({"error": str(e)}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    return jsonify({"error": "All models are currently experiencing high demand. Please try again in a few minutes."}), 503


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)