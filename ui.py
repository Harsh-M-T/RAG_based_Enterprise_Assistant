"""
Enterprise Knowledge Assistant - Streamlit UI

Interactive frontend for asking questions, viewing answers
with source citations, and providing feedback.
"""

import streamlit as st
import requests
import json
import time
from datetime import datetime

# ─── Page Configuration ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Enterprise Knowledge Assistant",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Header */
    .main-header {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 2rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .main-header p {
        color: rgba(255,255,255,0.65);
        font-size: 1rem;
        margin: 0.25rem 0 0 0;
    }

    /* Answer card */
    .answer-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 1.75rem;
        border-radius: 14px;
        border-left: 4px solid #00d2ff;
        margin: 1rem 0;
        color: #e0e0e0;
        line-height: 1.7;
    }

    /* Source chip */
    .source-chip {
        display: inline-block;
        background: rgba(0, 210, 255, 0.1);
        border: 1px solid rgba(0, 210, 255, 0.3);
        color: #00d2ff;
        padding: 0.35rem 0.85rem;
        border-radius: 20px;
        font-size: 0.85rem;
        margin: 0.25rem 0.35rem 0.25rem 0;
        font-weight: 500;
    }

    /* Confidence meter */
    .confidence-bar {
        height: 6px;
        border-radius: 3px;
        background: rgba(255,255,255,0.08);
        overflow: hidden;
        margin-top: 0.5rem;
    }
    .confidence-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.6s ease;
    }

    /* History item */
    .history-item {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        padding: 0.85rem 1rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: #b0b0b0;
    }
    .history-item:hover {
        background: rgba(0, 210, 255, 0.05);
        border-color: rgba(0, 210, 255, 0.15);
    }

    /* Status badges */
    .status-online { color: #00e676; }
    .status-offline { color: #ff5252; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0d1117;
    }
</style>
""", unsafe_allow_html=True)

# ─── Configuration ────────────────────────────────────────────────────────────
API_URL = "http://localhost:8000"

# ─── Session State ────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "feedback" not in st.session_state:
    st.session_state.feedback = {}


# ─── Helper Functions ─────────────────────────────────────────────────────────

def check_api_health() -> dict:
    """Check if the API server is running."""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        return resp.json()
    except Exception:
        return {"status": "offline", "index_loaded": False, "ollama_available": False}


def ask_question(question: str) -> dict:
    """Send a question to the API."""
    try:
        resp = requests.post(
            f"{API_URL}/ask",
            json={"question": question},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        return {
            "answer": "❌ Cannot connect to the API server. Make sure it's running with: `uvicorn app:app --reload`",
            "sources": [],
            "confidence": 0.0,
            "model": "N/A",
        }
    except requests.Timeout:
        return {
            "answer": "⏱️ The request timed out. The LLM may be loading or the query is too complex.",
            "sources": [],
            "confidence": 0.0,
            "model": "N/A",
        }
    except Exception as e:
        return {
            "answer": f"❌ Error: {str(e)}",
            "sources": [],
            "confidence": 0.0,
            "model": "N/A",
        }


def get_confidence_color(confidence: float) -> str:
    """Return a color based on confidence level."""
    if confidence >= 0.7:
        return "#00e676"
    elif confidence >= 0.4:
        return "#ffc107"
    else:
        return "#ff5252"


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ System Status")

    health = check_api_health()
    api_status = health.get("status", "offline")

    col1, col2 = st.columns(2)
    with col1:
        if api_status != "offline":
            st.markdown('<span class="status-online">● API Online</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-offline">● API Offline</span>', unsafe_allow_html=True)

    with col2:
        if health.get("ollama_available"):
            st.markdown('<span class="status-online">● LLM Ready</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-offline">● LLM Offline</span>', unsafe_allow_html=True)

    if health.get("index_loaded"):
        st.success("📚 Knowledge base loaded")
    else:
        st.warning("📚 Knowledge base not loaded. Run ingestion.py first.")

    st.markdown(f"**Model:** `{health.get('model', 'N/A')}`")

    st.markdown("---")
    st.markdown("### 💬 Conversation History")

    if st.button("🗑️ Clear History", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.feedback = {}
        st.rerun()

    for i, entry in enumerate(reversed(st.session_state.chat_history)):
        q_preview = entry["question"][:50] + ("..." if len(entry["question"]) > 50 else "")
        st.markdown(
            f'<div class="history-item">🔹 {q_preview}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 📊 Feedback Summary")
    total = len(st.session_state.feedback)
    positive = sum(1 for v in st.session_state.feedback.values() if v == "up")
    negative = total - positive
    st.markdown(f"👍 {positive}  |  👎 {negative}  |  Total: {total}")


# ─── Main Content ─────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🏢 Enterprise Knowledge Assistant</h1>
    <p>Ask questions about company policies, products, and procedures</p>
</div>
""", unsafe_allow_html=True)

# Question input
question = st.text_input(
    "Ask a question",
    placeholder="e.g., What is the employee leave policy?",
    label_visibility="collapsed",
)

col_ask, col_examples = st.columns([1, 3])
with col_ask:
    ask_clicked = st.button("🔍 Ask", type="primary", use_container_width=True)

with col_examples:
    st.markdown("**Try:** *What is the employee leave policy?* · *How do I onboard a new employee?* · *What is the refund policy?*")

# Process question
if ask_clicked and question:
    with st.spinner("🔍 Searching knowledge base and generating answer..."):
        start = time.time()
        result = ask_question(question)
        elapsed = time.time() - start

    # Store in history
    entry_id = len(st.session_state.chat_history)
    st.session_state.chat_history.append({
        "question": question,
        "result": result,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "elapsed": round(elapsed, 2),
    })

    # Display answer
    st.markdown("### 💡 Answer")
    st.markdown(
        f'<div class="answer-card">{result["answer"]}</div>',
        unsafe_allow_html=True,
    )

    # Sources
    sources = result.get("sources", [])
    if sources:
        st.markdown("### 📄 Sources")
        source_html = ""
        for s in sources:
            source_html += f'<span class="source-chip">📎 {s["document"]} — Page {s["page"]}</span>'
        st.markdown(source_html, unsafe_allow_html=True)

    # Confidence & Meta
    conf = result.get("confidence", 0.0)
    conf_color = get_confidence_color(conf)
    conf_pct = min(conf * 100, 100)

    meta_col1, meta_col2, meta_col3 = st.columns(3)
    with meta_col1:
        st.markdown(f"**Confidence:** {conf:.1%}")
        st.markdown(
            f'<div class="confidence-bar"><div class="confidence-fill" style="width:{conf_pct}%;background:{conf_color}"></div></div>',
            unsafe_allow_html=True,
        )
    with meta_col2:
        st.markdown(f"**Model:** `{result.get('model', 'N/A')}`")
    with meta_col3:
        st.markdown(f"**Response time:** {elapsed:.1f}s")

    # Feedback
    st.markdown("---")
    st.markdown("**Was this answer helpful?**")
    fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 6])
    with fb_col1:
        if st.button("👍", key=f"up_{entry_id}"):
            st.session_state.feedback[entry_id] = "up"
            st.success("Thanks for your feedback!")
    with fb_col2:
        if st.button("👎", key=f"down_{entry_id}"):
            st.session_state.feedback[entry_id] = "down"
            st.info("Thanks — we'll work to improve.")

elif ask_clicked and not question:
    st.warning("Please enter a question.")

# Show previous answers
if st.session_state.chat_history and not ask_clicked:
    st.markdown("### 📜 Recent Answers")
    for i, entry in enumerate(reversed(st.session_state.chat_history[-5:])):
        with st.expander(f"🔹 {entry['question']}  ({entry['timestamp']})"):
            st.markdown(
                f'<div class="answer-card">{entry["result"]["answer"]}</div>',
                unsafe_allow_html=True,
            )
            sources = entry["result"].get("sources", [])
            if sources:
                source_html = ""
                for s in sources:
                    source_html += f'<span class="source-chip">📎 {s["document"]} — Page {s["page"]}</span>'
                st.markdown(source_html, unsafe_allow_html=True)
