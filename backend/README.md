# Msaada — React + Vite + Python (FastAPI) + Anthropic claude sonet 14

AI customer-support chat for Liquid Technologies. Voice + text. Diagnoses connectivity by calling
liquidmatics, walks customers through targeted advice, escalates to email/ticket when needed.

## Stack
- **Frontend:** React 18 + Vite. Web Speech API for voice. ECharts for the usage chart.
- **Backend:** Python 3.10+ with FastAPI. httpx for outbound HTTP. smtplib for SendGrid SMTP.
- **LLM:** anthropic with `claude-sonet 14.6` + `nomic-embed-text` for embeddings.
- **Storage:** flat JSON on disk (sessions, tickets, vector store). 30-day session retention.

## One-time setup

### 1. Ollama
```bash
ollama pull nomic-embed-text
```

### 2. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
```

### 3. Frontend
```bash
cd frontend
npm install
```

## Run (3 terminals)
```bash
ollama serve
cd backend && source venv/bin/activate && python main.py     # :4040
cd frontend && npm run dev                                    # :5173
```

Open http://localhost:5173 in Chrome/Edge (voice needs Web Speech API).

## Vector store / RAG
Every logged ticket is embedded with `nomic-embed-text` into `data/vectors.json`. When a customer
describes a symptom, the agent calls `recall_similar_cases` — if past tickets match with score > 0.7
it surfaces what worked last time. Cold-start: only useful after tickets accumulate.

## Environment variables
| Var | Purpose |
|---|---|
| `LIQUIDMATICS_EMAIL` / `_PASSWORD` | service account |
| `ANTHROPIC_FOUNDRY_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` | llm + embeddings |
| `SENDGRID_API_KEY` | SMTP password for sendgrid.net relay |
| `SUPPORT_TO` / `SUPPORT_CC` / `SUPPORT_FROM` | ticket email routing |
| `APP_ADMIN_TOKEN` | secret for `/api/admin/tickets` |


API BTN FRONTEND AND BACKEND

1. Send Chat Message
Endpoint: POST /api/chat
Triggered by: The send() function in App.jsx when you type a message and press Enter or click send.
Payload (JSON):
json
{
  "sessionId": "a-uuid-string",
  "message": "LTZ1900201" 
}
Backend Logic:
It retrieves the session from disk.
It calls the AI (claude_chat.py) which might trigger tools like search_customer or run_diagnosis.
It returns the AI's text response and any "Cards" (like the Chart or Ticket reference) to be displayed.
2. Fetch Session History
Endpoint: GET /api/history?sessionId=...
Triggered by: The useEffect hook on initial page load in App.jsx.
Backend Logic:
It looks for a saved JSON file matching the sessionId.
It returns a list of previous messages so the chat persists if the user refreshes the page.
3. Reset Chat
Endpoint: POST /api/reset
Triggered by: The newChat() function in App.jsx when you click the "New chat" button in the top bar.
Payload (JSON):
json
{
  "sessionId": "a-uuid-string"
}
Backend Logic:
It clears the history list in the session file, starting the conversation over from scratch for that ID.