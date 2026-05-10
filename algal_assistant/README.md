# Algal Assistant Setup

Step 1: Install dependencies
pip install openai chromadb

Step 2: Set OpenAI API key
Windows: set OPENAI_API_KEY=your-key-here
Mac/Linux: export OPENAI_API_KEY=your-key-here

Step 3: Build knowledge base (run once)
python algal_assistant/build_knowledge_base.py

Step 4: Start the API
uvicorn api.main:app --reload --port 8000

Step 5: Test the assistant
POST http://localhost:8000/api/algal-assistant
Body: {"question": "Is Glenelg Beach safe today?"}

Example questions:
- Is it safe to take students to Glenelg Beach this Friday?
- Which SA beaches have the lowest bloom risk in Term 2?
- What is the current Karenia cell count at Henley Beach?
- Generate a risk assessment for Port Noarlunga excursion
- What is the 72 hour bloom forecast for Adelaide beaches?
- Which months are safest for coastal school excursions in SA?
