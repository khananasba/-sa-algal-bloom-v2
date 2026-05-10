"""
RAG engine for the Algal Assistant.

Handles knowledge base chunking, ChromaDB in-memory vector store,
live API data retrieval, and prompt construction for GPT-4o.

Data priority order (always follow strictly):
  1. Ground truth cell counts  — SA Gov field water sampling (highest accuracy)
  2. Beach safety scores       — calculated from ground truth
  3. Live weather              — BOM Open-Meteo
  4. Satellite SFABI           — supporting context only
"""
import os
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# In-memory ChromaDB singleton — built once per API worker, reused on every call.
_collection = None


# ── 1. Document loading & chunking ────────────────────────────────────────────

def load_and_chunk_docs(knowledge_dir: str) -> list[dict]:
    """
    Read all .txt files from knowledge_dir and split into overlapping chunks.

    Args:
        knowledge_dir: Absolute path to directory containing .txt files.

    Returns:
        List of dicts with keys: text, source, chunk_id.
    """
    chunks: list[dict] = []
    chunk_size = 500
    overlap = 100

    kb_path = Path(knowledge_dir)
    txt_files = list(kb_path.glob("*.txt"))
    print(f"[RAG] Found {len(txt_files)} knowledge files in {knowledge_dir}")

    for txt_file in txt_files:
        try:
            text = txt_file.read_text(encoding="utf-8")
            source = txt_file.name
            start = 0
            chunk_id = 0
            while start < len(text):
                end = start + chunk_size
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunks.append({
                        "text": chunk_text,
                        "source": source,
                        "chunk_id": f"{source}_{chunk_id}",
                    })
                chunk_id += 1
                start = end - overlap
        except Exception as e:
            logger.error(f"load_and_chunk_docs: error reading {txt_file}: {e}")

    print(f"[RAG] Created {len(chunks)} chunks from {len(txt_files)} files")
    return chunks


# ── 2. ChromaDB in-memory collection singleton ────────────────────────────────

def get_or_build_collection():
    """
    Return the in-memory ChromaDB collection, building it on first call.

    Uses module-level _collection singleton so the expensive embedding step
    only happens once per API worker process.

    Returns:
        chromadb Collection ready for querying, or None if build fails.
    """
    global _collection
    if _collection is not None:
        return _collection

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error(
            "get_or_build_collection: OPENAI_API_KEY not set — cannot build collection"
        )
        return None

    try:
        import chromadb
        from openai import OpenAI

        knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge_base")
        chunks = load_and_chunk_docs(knowledge_dir)
        if not chunks:
            logger.warning("get_or_build_collection: no chunks — check knowledge_base/")
            return None

        client = OpenAI(api_key=api_key)
        chroma_client = chromadb.EphemeralClient()
        collection = chroma_client.create_collection("algal_knowledge")

        texts = [c["text"] for c in chunks]
        ids = [c["chunk_id"] for c in chunks]
        metadatas = [{"source": c["source"]} for c in chunks]

        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        embeddings = [e.embedding for e in response.data]
        collection.add(documents=texts, embeddings=embeddings, ids=ids, metadatas=metadatas)

        file_count = len({c["source"] for c in chunks})
        logger.info(f"[RAG] Collection ready: {len(chunks)} chunks from {file_count} files")
        _collection = collection

    except Exception as e:
        logger.error(f"get_or_build_collection failed: {e}")

    return _collection


# ── 3. Retrieval ──────────────────────────────────────────────────────────────

def retrieve_context(question: str, n: int = 3) -> list[str]:
    """
    Query ChromaDB for the top n chunks most relevant to question.

    Args:
        question: User's question string.
        n:        Number of chunks to retrieve.

    Returns:
        List of relevant text strings. Empty list on any error.
    """
    try:
        from openai import OpenAI

        collection = get_or_build_collection()
        if collection is None:
            return []

        api_key = os.environ.get("OPENAI_API_KEY", "")
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[question],
        )
        query_embedding = response.data[0].embedding
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n, collection.count()),
        )
        return results["documents"][0] if results["documents"] else []
    except Exception as e:
        logger.warning(f"retrieve_context failed: {e}")
        return []


# ── 4. Live data (delegates to live_context.py) ───────────────────────────────

def get_live_context() -> str:
    """
    Fetch live platform data from the API in priority order.

    Delegates to live_context.fetch_live_context() with the API_BASE_URL
    from the environment (defaults to http://localhost:8000/api).

    Returns:
        Formatted string with ground truth, safety scores, weather, satellite.
        Empty string if the API is unreachable.
    """
    from algal_assistant.live_context import fetch_live_context
    base = os.environ.get("API_BASE_URL", "http://localhost:8000/api")
    return fetch_live_context(base)


# ── 5. Prompt builder ─────────────────────────────────────────────────────────

def build_prompt(question: str, live_data: str, chunks: list[str]) -> list[dict]:
    """
    Build OpenAI chat messages for GPT-4o from live data + knowledge chunks.

    Args:
        question:  User's question.
        live_data: Formatted string from get_live_context().
        chunks:    Retrieved knowledge base text chunks.

    Returns:
        List of message dicts ready for OpenAI chat completion API.
    """
    today = date.today().strftime("%d %B %Y")

    system_msg = (
        "You are the Algal Assistant for the SA Algal Bloom Monitor platform.\n"
        "You help school principals teachers outdoor education coordinators\n"
        "and aquaculture operators make safe decisions about SA coastal waters.\n\n"
        "DATA PRIORITY RULES — follow these strictly:\n"
        "1. Always lead answers with ground truth water sampling data first.\n"
        "   Ground truth means actual Karenia cell counts in cells per litre\n"
        "   from SA Government field scientists physically testing water samples.\n"
        "   This is the most accurate data source available.\n"
        "2. Cite beach safety scores second as they are calculated from ground truth.\n"
        "3. Mention weather conditions third as supporting context.\n"
        "4. Mention satellite SFABI data last and always label it as supporting\n"
        "   context — never as the primary evidence for safety decisions.\n"
        "5. If both ground truth and satellite data are available for a location\n"
        "   always lead with the ground truth cell count number.\n\n"
        "ANSWER RULES:\n"
        "Always cite SA Health as the official decision authority on beach safety.\n"
        "Keep answers concise practical and actionable.\n"
        "Always include the actual cell count number when discussing a beach.\n"
        "Never output placeholder text like insert date here or enter score here.\n"
        f"Always use today's actual date which is: {today}\n\n"
        "When generating a risk assessment document use this structure:\n"
        f"Date: {today}\n"
        "Beach or Location: [specific name]\n"
        "Current Safety Score: [number]/100\n"
        "Karenia Cell Count: [number] cells per litre — from ground truth sampling\n"
        "SA Health Threshold Status: [Safe / Caution / Danger]\n"
        "Current Weather: Wind [speed] km/h SST [temp] degrees C\n"
        "Recommendation: [Safe to proceed / Caution / Do Not Use]\n"
        "Notes: [specific relevant notes]\n"
        f"Generated by Algal Assistant on {today}"
    )

    knowledge = "\n---\n".join(chunks) if chunks else "No knowledge base available."
    user_content = (
        "=== LIVE PLATFORM DATA ===\n"
        f"{live_data or 'API not available.'}\n\n"
        "=== RELEVANT KNOWLEDGE BASE ===\n"
        f"{knowledge}\n\n"
        "=== USER QUESTION ===\n"
        f"{question}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]
