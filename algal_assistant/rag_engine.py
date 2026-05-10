import os
import json
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# In-memory ChromaDB collection — built once per API process, reused on every request.
# Render free tier resets the filesystem on each deploy so persistent disk storage
# is not reliable. EphemeralClient stores everything in RAM for the process lifetime.
_chroma_collection = None


def get_or_build_collection():
    """
    Return the in-memory ChromaDB collection, building it from the knowledge
    base .txt files if it has not been built yet this process.

    The collection is created exactly once per API worker process. Subsequent
    calls return the cached reference immediately without re-embedding.

    Returns:
        chromadb Collection, or None if knowledge_base/ has no .txt files
        or if OpenAI credentials are missing.
    """
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection

    try:
        import chromadb
        from openai import OpenAI

        knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge_base")
        chunks = load_and_chunk_docs(knowledge_dir)
        if not chunks:
            logger.warning("get_or_build_collection: no chunks found in knowledge_base/")
            return None

        client = OpenAI()
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

        collection.add(
            documents=texts,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )
        file_count = len({c["source"] for c in chunks})
        logger.info(
            f"In-memory knowledge base built: {len(chunks)} chunks from {file_count} files"
        )
        _chroma_collection = collection
    except Exception as e:
        logger.error(f"get_or_build_collection failed: {e}")

    return _chroma_collection


def load_and_chunk_docs(knowledge_dir: str) -> list[dict]:
    """
    Read all .txt files from knowledge_dir and split into overlapping chunks.

    Args:
        knowledge_dir: Path to directory containing .txt knowledge files.

    Returns:
        List of dicts with keys: text, source, chunk_id.
    """
    chunks = []
    chunk_size = 500
    overlap = 100

    for txt_file in Path(knowledge_dir).glob("*.txt"):
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
            logger.error(f"Error reading {txt_file}: {e}")

    return chunks


def build_vector_store(chunks: list[dict]) -> None:
    """
    Create OpenAI embeddings for chunks and persist them in ChromaDB on disk.
    Used by build_knowledge_base.py for local development only.
    On Render, get_or_build_collection() builds an in-memory store instead.

    Args:
        chunks: List of chunk dicts from load_and_chunk_docs().
    """
    import chromadb
    from openai import OpenAI

    client = OpenAI()
    chroma_path = os.path.join(os.path.dirname(__file__), "chroma_db")
    chroma_client = chromadb.PersistentClient(path=chroma_path)

    try:
        chroma_client.delete_collection("algal_knowledge")
    except Exception:
        pass

    collection = chroma_client.create_collection("algal_knowledge")

    texts = [c["text"] for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    metadatas = [{"source": c["source"]} for c in chunks]

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    embeddings = [e.embedding for e in response.data]

    collection.add(
        documents=texts,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )
    print(f"Stored {len(chunks)} chunks in ChromaDB at {chroma_path}")


def retrieve_context(question: str, n: int = 3) -> list[str]:
    """
    Query the in-memory ChromaDB collection for the top n chunks most
    relevant to question. Calls get_or_build_collection() which builds
    the collection on first call and reuses it on subsequent calls.

    Args:
        question: The user's question string.
        n:        Number of chunks to return.

    Returns:
        List of relevant text chunks. Empty list if collection unavailable.
    """
    try:
        from openai import OpenAI

        collection = get_or_build_collection()
        if collection is None:
            return []

        client = OpenAI()
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


def _format_cell_counts(data: dict) -> str:
    """
    Format all cell count readings grouped by severity for assistant context.

    Args:
        data: JSON response from /api/cell-counts.

    Returns:
        Human-readable string grouped as Critical / High / Medium / Low.
    """
    readings = data.get("readings", [])
    if not readings:
        return "No cell count readings available."

    groups: dict[str, list[str]] = {
        "Critical": [], "High": [], "Medium": [], "Low": [],
    }
    for r in readings:
        beach = r.get("beach_name", "Unknown")
        count = r.get("cell_count_per_litre", 0)
        sev = r.get("severity", "Low")
        entry = f"  {beach}: {count:,} cells/L"
        if sev in groups:
            groups[sev].append(entry)
        else:
            groups["Low"].append(entry)

    lines = [f"Total readings: {len(readings)}"]
    for sev in ("Critical", "High", "Medium", "Low"):
        if groups[sev]:
            lines.append(f"\n{sev} ({len(groups[sev])} beaches):")
            lines.extend(groups[sev])
    return "\n".join(lines)


def get_live_context() -> str:
    """
    Fetch live data from the local API in priority order:
    1. Ground truth cell counts (highest accuracy — SA Gov field sampling)
    2. Beach safety scores (derived from ground truth)
    3. Weather data
    4. Satellite data is injected separately in build_prompt()

    Returns:
        Formatted string with current platform data.
        Empty string if the API is unreachable.
    """
    base = os.environ.get("API_BASE_URL", "http://localhost:8000/api")
    parts = []

    # --- 1. Ground truth cell counts (highest priority) ---
    try:
        r = requests.get(base + "/cell-counts", timeout=5)
        r.raise_for_status()
        data = r.json()
        parts.append(
            "[Ground Truth Cell Counts — SA Gov Field Sampling (HIGHEST PRIORITY)]\n"
            "These are actual water samples tested by SA Government field scientists.\n"
            "Cell counts are measured in cells per litre under microscope.\n"
            + _format_cell_counts(data)
        )
    except Exception as e:
        logger.warning(f"Live context: cell-counts fetch failed: {e}")

    # --- 2. Beach safety scores (derived from ground truth) ---
    try:
        r = requests.get(base + "/beach-safety", timeout=5)
        r.raise_for_status()
        data = r.json()
        scores = data.get("scores", [])
        lines = [f"Beach Safety Scores ({len(scores)} beaches):"]
        for s in scores:
            lines.append(
                f"  {s.get('beach')}: {s.get('score')}/100 [{s.get('label')}]"
                f" — {s.get('cell_count', 0):,} cells/L"
            )
        parts.append("[Beach Safety Scores — Calculated from Ground Truth]\n" + "\n".join(lines))
    except Exception as e:
        logger.warning(f"Live context: beach-safety fetch failed: {e}")

    # --- 3. Weather data ---
    try:
        r = requests.get(base + "/weather", timeout=5)
        r.raise_for_status()
        data = r.json()
        readings = data.get("readings", [])[:5]
        lines = ["Top 5 coastal weather readings:"]
        for w in readings:
            lines.append(
                f"  {w.get('location_name')}: wind {w.get('wind_speed')} km/h,"
                f" SST {w.get('sea_surface_temp')}°C,"
                f" waves {w.get('wave_height')} m"
            )
        parts.append("[Weather]\n" + "\n".join(lines))
    except Exception as e:
        logger.warning(f"Live context: weather fetch failed: {e}")

    return "\n\n".join(parts)


def build_prompt(question: str, live_data: str, chunks: list[str]) -> list[dict]:
    """
    Build OpenAI chat messages list combining live data, knowledge, and question.
    Live data is structured in priority order:
      1. Ground truth cell counts  2. Beach safety scores  3. Weather  4. Satellite

    Args:
        question:  The user's question.
        live_data: Formatted string from get_live_context().
        chunks:    Retrieved knowledge base text chunks.

    Returns:
        List of message dicts ready for OpenAI chat completion.
    """
    from datetime import date
    today = date.today().strftime("%d %B %Y")

    system_msg = (
        f"Today's date is {today}.\n"
        "You are the Algal Assistant for South Australia coastal safety "
        "monitoring platform. You help school principals, teachers, outdoor "
        "education coordinators, and aquaculture operators make informed "
        "decisions about coastal safety and bloom conditions.\n"
        "Always cite SA Health as the official decision authority on beach safety.\n"
        "Ground your answers in the live data provided when available.\n"
        "Keep answers concise, practical and actionable.\n"
        "Never output placeholder text such as [Insert Date] or [Enter Date Here] — "
        f"always use the actual date: {today}.\n"
        "When answering questions always prioritise ground truth water sampling data "
        "(Karenia cell counts in cells per litre from SA Government field testing) "
        "over satellite SFABI readings. "
        "Satellite data supports the answer but ground truth is more accurate. "
        "Always cite the cell count in cells per litre from ground sampling as the "
        "primary evidence. "
        "If both sources are available always lead with the ground truth cell count first.\n"
        "When generating a risk assessment document structure it as:\n"
        f"Date: {today}, Beach or Location, Current Safety Score out of 100, "
        "Karenia Cell Count in cells per litre, SA Health Threshold Status, "
        "Current Weather Conditions, Recommendation which is Safe or Caution "
        "or Do Not Use, Notes, Generated by Algal Assistant."
    )

    knowledge = "\n---\n".join(chunks) if chunks else "No knowledge base available."
    satellite_note = (
        "[Satellite Data — Supporting Context Only]\n"
        "SFABI and NDCI from Sentinel-2 via Google Earth Engine.\n"
        "Satellite estimates bloom presence across the full SA coastline "
        "but cannot measure exact Karenia cell counts.\n"
        "Ground truth cell counts above take priority over satellite readings."
    )
    user_content = (
        "LIVE PLATFORM DATA (in priority order):\n\n"
        f"{live_data or 'API not available.'}\n\n"
        f"{satellite_note}\n\n"
        f"KNOWLEDGE BASE:\n{knowledge}\n\n"
        f"QUESTION: {question}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]
