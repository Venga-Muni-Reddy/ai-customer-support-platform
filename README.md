# SupportPilot - AI customer support with human fallback

FastAPI + LangGraph + LangChain + PostgreSQL + React.

A business pastes its help docs. Customers ask questions in a chat page. A LangGraph pipeline answers from the docs, a second agent fact-checks the answer, and low-confidence questions go to a human queue instead of the customer.

## Agent pipeline (LangGraph)
1. **Retriever** - PostgreSQL full-text search (`tsvector` + `ts_rank_cd`) over the workspace's document chunks. No relevant passage means escalate without calling the LLM.
2. **Answerer** (LangChain prompt + chat model) - answers only from the numbered passages with citations, or returns `INSUFFICIENT`.
3. **Verifier** (separate LLM call) - returns JSON `{supported, score, unsupported_claims}` for the draft against the sources. Unparseable output counts as score 0.
4. **Router** - score >= threshold (default 70) replies; otherwise the question is escalated. The unverified draft is never shown to the customer.

## Features
- Customer chat with citations and an expandable agent trace
- Escalation queue; human replies show up in the customer's chat; optional "save Q&A to knowledge base"
- Dashboard stats: questions, auto-resolved rate, open escalations, average confidence
- Multi-workspace: anyone can create a workspace and get an admin key (stored as a SHA-256 hash)
- Rate limits and caps to keep the free demo safe

## Limits (honest)
- Retrieval is keyword full-text search, not vector embeddings
- Plain-text docs only (paste text); no PDF upload
- Confidence comes from an LLM verifier, so it is a signal, not a guarantee
- No embeddable widget or email integration yet

## Run locally
```
export DATABASE_URL=postgresql://...  OPENROUTER_API_KEY=...
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --port 8000
```
Env: `OPENROUTER_API_KEY`, `DATABASE_URL`, optional `OPENROUTER_MODEL`, `CONFIDENCE_THRESHOLD`, `PER_IP_CHAT_PER_HOUR`, `GLOBAL_CHAT_PER_DAY`.
