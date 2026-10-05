"""LangGraph pipeline: retriever -> answerer (LLM) -> verifier (LLM) -> router (respond | escalate)."""
import os, json, re, time
from typing import TypedDict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from . import db

MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS_PER_CALL", "500"))
THRESHOLD = int(os.environ.get("CONFIDENCE_THRESHOLD", "70"))

def llm():
    return ChatOpenAI(model=MODEL, api_key=os.environ.get("OPENROUTER_API_KEY", ""), base_url="https://openrouter.ai/api/v1",
                      temperature=0, max_tokens=MAX_TOKENS, timeout=45, max_retries=1)

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are a customer support agent for {company}. Answer the customer's question using ONLY the numbered context below. "
               "Cite the context numbers you used like [1]. Be concise and friendly (max 5 sentences). "
               "If the context does not contain the answer, reply with exactly: INSUFFICIENT"),
    ("human", "Context:\n{context}\n\nCustomer question: {question}"),
])

VERIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are a strict fact-checker. Given source passages and a draft support answer, decide whether EVERY factual claim in the answer "
               "is directly supported by the sources. Reply with JSON only, no prose: "
               '{{"supported": true|false, "score": <0-100 confidence the answer is fully supported and answers the question>, '
               '"unsupported_claims": ["..."]}}'),
    ("human", "Sources:\n{context}\n\nCustomer question: {question}\n\nDraft answer: {answer}"),
])

class S(TypedDict, total=False):
    ws_id: int
    company: str
    question: str
    chunks: list
    context: str
    answer: str
    verdict: dict
    confidence: int
    decision: str
    reason: str
    trace: list

def _t(state, agent, detail, ms):
    state.setdefault("trace", []).append({"agent": agent, "detail": detail, "ms": ms})

def retriever(s: S):
    t = time.time()
    rows = db.search_chunks(s["ws_id"], s["question"])
    s["chunks"] = [{"id": r["id"], "title": r["title"], "text": r["content"], "score": float(r["score"])} for r in rows]
    s["context"] = "\n\n".join(f"[{i+1}] ({c['title']}) {c['text']}" for i, c in enumerate(s["chunks"]))
    _t(s, "Retriever", f"PostgreSQL full-text search found {len(rows)} passage(s)", int((time.time()-t)*1000))
    return s

def after_retrieve(s: S):
    return "answer" if s["chunks"] else "no_docs"

def no_docs(s: S):
    s.update(answer="", confidence=0, decision="escalate", reason="No relevant passage in the knowledge base", verdict=None)
    _t(s, "Router", "Escalated without calling the LLM: nothing relevant to ground an answer", 0)
    return s

def answerer(s: S):
    t = time.time()
    msg = (ANSWER_PROMPT | llm()).invoke({"company": s["company"], "context": s["context"], "question": s["question"]})
    s["answer"] = (msg.content or "").strip()
    _t(s, "Answerer", "Drafted an answer from the retrieved passages", int((time.time()-t)*1000))
    return s

def after_answer(s: S):
    return "insufficient" if s["answer"].upper().startswith("INSUFFICIENT") or not s["answer"] else "verify"

def insufficient(s: S):
    s.update(confidence=0, decision="escalate", reason="Answerer found the documents do not cover this question", verdict=None)
    _t(s, "Router", "Escalated: answerer reported insufficient context", 0)
    return s

def parse_json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def verifier(s: S):
    t = time.time()
    msg = (VERIFY_PROMPT | llm()).invoke({"context": s["context"], "question": s["question"], "answer": s["answer"]})
    v = parse_json(msg.content or "")
    if not v or "score" not in v:
        v = {"supported": False, "score": 0, "unsupported_claims": ["verifier output could not be parsed"]}
    try:
        score = max(0, min(100, int(v.get("score", 0))))
    except Exception:
        score = 0
    if not v.get("supported", False):
        score = min(score, THRESHOLD - 1)
    s["verdict"] = {"supported": bool(v.get("supported")), "score": score, "unsupported_claims": v.get("unsupported_claims", [])[:5]}
    s["confidence"] = score
    _t(s, "Verifier", f"Independent check of the draft against sources: score {score}/100", int((time.time()-t)*1000))
    return s

def router(s: S):
    if s["confidence"] >= THRESHOLD:
        s.update(decision="respond", reason="")
        _t(s, "Router", f"Confidence {s['confidence']} >= {THRESHOLD}: answered automatically", 0)
    else:
        s.update(decision="escalate", reason=f"Verifier confidence {s['confidence']} below threshold {THRESHOLD}")
        _t(s, "Router", f"Confidence {s['confidence']} < {THRESHOLD}: escalated to human queue", 0)
    return s

g = StateGraph(S)
for n, f in [("retrieve", retriever), ("no_docs", no_docs), ("answer", answerer), ("insufficient", insufficient), ("verify", verifier), ("route", router)]:
    g.add_node(n, f)
g.set_entry_point("retrieve")
g.add_conditional_edges("retrieve", after_retrieve, {"answer": "answer", "no_docs": "no_docs"})
g.add_conditional_edges("answer", after_answer, {"verify": "verify", "insufficient": "insufficient"})
g.add_edge("verify", "route")
for n in ("no_docs", "insufficient", "route"):
    g.add_edge(n, END)
GRAPH = g.compile()

def run(ws_id, company, question):
    return GRAPH.invoke({"ws_id": ws_id, "company": company, "question": question, "trace": []})
