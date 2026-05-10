"""
Standalone script to build the ChromaDB vector store from knowledge base files.
Run once before starting the API:
    python algal_assistant/build_knowledge_base.py
"""
import os
import sys

# Add project root to path so imports work when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algal_assistant.rag_engine import load_and_chunk_docs, build_vector_store


def run() -> None:
    """Build ChromaDB vector store from knowledge base text files."""
    knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge_base")

    print(f"Loading documents from: {knowledge_dir}")
    chunks = load_and_chunk_docs(knowledge_dir)

    files_loaded = len({c["source"] for c in chunks})
    print(f"Files loaded: {files_loaded}")
    print(f"Chunks created: {len(chunks)}")

    if not chunks:
        print("No chunks found — check that knowledge_base/ contains .txt files.")
        return

    print("Building vector store (this may take a moment)...")
    build_vector_store(chunks)
    print("Knowledge base build complete.")


if __name__ == "__main__":
    run()
