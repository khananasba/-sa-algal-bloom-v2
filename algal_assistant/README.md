# Algal Assistant — RAG Setup Guide

RAG (Retrieval Augmented Generation) AI assistant for the SA Algal Bloom Monitor platform.

---

## Data Priority Order

| Priority | Source | Description |
|---|---|---|
| 1 | Ground truth CSV | SA Gov field water sampling — highest accuracy |
| 2 | Beach safety scores | Calculated from ground truth cell counts |
| 3 | Live weather | BOM Open-Meteo (wind, SST, wave height) |
| 4 | Satellite SFABI | Sentinel-2 via GEE — supporting context only |

---

## Setup Steps

### Step 1 — Install dependencies
```
pip install openai chromadb
```

### Step 2 — Set environment variables in `.env`
```
OPENAI_API_KEY=your-openai-key
API_BASE_URL=https://sa-algal-bloom-v2-api.onrender.com/api
```

### Step 3 — Test the knowledge base locally
```
python algal_assistant/build_knowledge_base.py
```

### Step 4 — Start the API
```
uvicorn api.main:app --reload --port 8000
```

### Step 5 — Test the endpoint
```
POST http://localhost:8000/api/algal-assistant
Body: {"question": "Which beaches are Critical right now?"}
```

---

## Example Questions

- Which SA beaches have Critical Karenia readings right now?
- Is it safe to take Year 10 students to Glenelg Beach this Friday?
- What is the ground truth cell count at Boston Bay?
- Which beaches are safest for a school excursion in Term 2?
- Generate a risk assessment for Port Noarlunga excursion next Tuesday
- How does satellite data support the ground truth readings?
- What is the current bloom situation at Eyre Peninsula?
- What does the SFABI reading of 0.4358 mean for coastal safety?

---

## Architecture

```
User question
    │
    ├── retrieve_context()   → ChromaDB in-memory (text-embedding-3-small)
    ├── get_live_context()   → Live API: cell-counts, beach-safety, weather
    │
    └── build_prompt()       → GPT-4o (max_tokens=800)
                                    │
                                    └── Answer grounded in ground truth + live data
```

---

## Knowledge Base Files

| File | Content |
|---|---|
| `sa_health_guidelines.txt` | Official SA Health Karenia thresholds and health warnings |
| `bloom_patterns.txt` | Historical hotspots, seasonal patterns, ground truth priority |
| `sace_curriculum.txt` | SACE excursion guidance and risk assessment template |
| `aquaculture.txt` | Tuna farm mortality thresholds, PIRSA info |
| `satellite.txt` | SFABI/NDCI explained, satellite vs ground truth comparison |

---

## Render Deployment Notes

- The ChromaDB collection is built **in-memory** on first request.
- Building takes approximately 5 seconds (OpenAI embeddings API call).
- Add these as Render environment variables:
  - `OPENAI_API_KEY`
  - `API_BASE_URL` → `https://sa-algal-bloom-v2-api.onrender.com/api`
- No disk persistence needed — EphemeralClient resets cleanly on each deploy.
