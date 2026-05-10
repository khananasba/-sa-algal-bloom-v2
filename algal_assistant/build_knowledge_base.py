"""
Standalone script to build and test the ChromaDB knowledge base.

Usage:
    python algal_assistant/build_knowledge_base.py

Requires OPENAI_API_KEY in environment or .env file.
"""
import os
import sys

# Make project root importable when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from algal_assistant.rag_engine import (
    load_and_chunk_docs,
    get_or_build_collection,
    retrieve_context,
)


def run() -> None:
    """
    Build the ChromaDB collection from knowledge base files and run a test query.

    Prints file count, chunk count, and confirms retrieval is working.
    """
    knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge_base")

    print("=" * 60)
    print("Algal Assistant — Knowledge Base Builder")
    print("=" * 60)

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        print("Add it to your .env file and try again.")
        sys.exit(1)

    # Step 1: Count files and chunks
    chunks = load_and_chunk_docs(knowledge_dir)
    files_loaded = len({c["source"] for c in chunks})
    print(f"\nFiles loaded:   {files_loaded}")
    print(f"Chunks created: {len(chunks)}")

    if not chunks:
        print("ERROR: No chunks found. Check that knowledge_base/ contains .txt files.")
        sys.exit(1)

    # Step 2: Build in-memory ChromaDB collection
    print("\nBuilding in-memory ChromaDB collection (calling OpenAI embeddings)...")
    collection = get_or_build_collection()

    if collection is None:
        print("ERROR: Collection build failed — check OPENAI_API_KEY and network.")
        sys.exit(1)

    print(f"Collection ready: {collection.count()} chunks indexed in ChromaDB.")

    # Step 3: Test query
    test_q = "Which beaches are Critical right now?"
    print(f"\nTest query: '{test_q}'")
    results = retrieve_context(test_q, n=2)
    print(f"Retrieved {len(results)} chunks:")
    for i, chunk in enumerate(results, 1):
        preview = chunk[:120].replace("\n", " ")
        print(f"  [{i}] {preview}...")

    print("\n[OK] Knowledge base is working correctly.")
    print("Start the API with: uvicorn api.main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    run()
