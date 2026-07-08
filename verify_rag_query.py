from algal_assistant.rag_engine import get_live_context
live_data = get_live_context(question="is henley beach safe to swim today")
print("=== LIVE DATA FOR HENLEY ===")
print(live_data)
