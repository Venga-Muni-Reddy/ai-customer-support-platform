import os, time, json, hashlib, secrets, re
from collections import defaultdict, deque
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import bcrypt
from . import db, agents, seed

PER_IP_CHAT_HOUR = int(os.environ.get("PER_IP_CHAT_PER_HOUR", "20"))
GLOBAL_CHAT_DAY = int(os.environ.get("GLOBAL_CHAT_PER_DAY", "300"))
MAX_WORKSPACES = int(os.environ.get("MAX_WORKSPACES", "200"))
MAX_USERS = int(os.environ.get("MAX_USERS", "500"))
MAX_DOCS = 12
MAX_DOC_CHARS = 20000
DEMO_KEY = "demo-admin"

app = FastAPI(title="AI Customer Support Platform")
_hits = defaultdict(deque)
_day = {"d": "", "n": 0}

def ip(req: Request):
    return (req.headers.get("x-forwarded-for") or req.client.host or "?").split(",")[0].strip()

def limit(key, n, per):
    now = time.time(); dq = _hits[key]
    while dq and now - dq[0] > per: dq.popleft()
    if len(dq) >= n: raise HTTPException(429, "Rate limit reached. Please try again later.")
    dq.append(now)

def h(x): return hashlib.sha256(x.encode()).hexdigest()

@app.on_event("startup")
def startup():
    db.init()
    if not db.q("SELECT 1 FROM workspaces WHERE slug='demo'", one=True):
        w = db.q("INSERT INTO workspaces (slug,name,admin_hash,is_demo) VALUES ('demo',%s,%s,TRUE) RETURNING id", (seed.DEMO_NAME, h(DEMO_KEY)), one=True)
        for t, body in seed.DOCS:
            db.add_document(w["id"], t, body, source="seed")

def ws_or_404(slug):
    w = db.q("SELECT * FROM workspaces WHERE slug=%s", (slug,), one=True)
    if not w: raise HTTPException(404, "Workspace not found")
    return w

SESSION_DAYS = 14
COOKIE = "sp_session"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MAX_WS_PER_USER = 3

def current_user(req: Request):
    tok = req.cookies.get(COOKIE)
    if not tok: return None
    return db.q("""SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash=%s AND s.expires_at > now()""", (h(tok),), one=True)

def need_user(req: Request):
    u = current_user(req)
    if not u: raise HTTPException(401, "Please sign in")
    return u

def admin(slug, req: Request, write=True):
    """Dashboard access: the demo workspace is public and read-only; every other workspace is owner-only."""
    w = ws_or_404(slug)
    if w["is_demo"]:
        if write: raise HTTPException(403, "The demo dashboard is read-only. Sign up to create your own workspace.")
        return w
    u = need_user(req)
    if w["owner_id"] != u["id"]: raise HTTPException(403, "This workspace belongs to another account")
    return w

@app.get("/api/health")
def health(): return {"ok": True}

class Creds(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=72)

def start_session(resp: Response, req: Request, uid: int):
    tok = secrets.token_urlsafe(32)
    db.q("INSERT INTO sessions (token_hash,user_id,expires_at) VALUES (%s,%s, now() + make_interval(days => %s))", (h(tok), uid, SESSION_DAYS))
    db.q("DELETE FROM sessions WHERE expires_at < now()")
    secure = req.headers.get("x-forwarded-proto", req.url.scheme) == "https"
    resp.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")

@app.post("/api/auth/signup")
def signup(b: Creds, req: Request, resp: Response):
    limit("signup:" + ip(req), 10, 3600)
    email = b.email.strip().lower()
    if not EMAIL_RE.match(email): raise HTTPException(400, "Enter a valid email address")
    if len(b.password.encode()) > 72: raise HTTPException(400, "Password must be at most 72 bytes")
    if db.q("SELECT count(*) AS n FROM users", one=True)["n"] >= MAX_USERS:
        raise HTTPException(429, "Signups are full on this free demo")
    pw = bcrypt.hashpw(b.password.encode(), bcrypt.gensalt()).decode()
    u = db.q("INSERT INTO users (email,pw_hash) VALUES (%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id", (email, pw), one=True)
    if not u: raise HTTPException(409, "An account with this email already exists")
    start_session(resp, req, u["id"])
    return {"email": email}

@app.post("/api/auth/login")
def login(b: Creds, req: Request, resp: Response):
    limit("login:" + ip(req), 15, 900)
    u = db.q("SELECT * FROM users WHERE email=%s", (b.email.strip().lower(),), one=True)
    ok = False
    try: ok = bool(u) and bcrypt.checkpw(b.password.encode(), u["pw_hash"].encode())
    except Exception: ok = False
    if not ok: raise HTTPException(401, "Wrong email or password")
    start_session(resp, req, u["id"])
    return {"email": u["email"]}

@app.post("/api/auth/logout")
def logout(req: Request, resp: Response):
    tok = req.cookies.get(COOKIE)
    if tok: db.q("DELETE FROM sessions WHERE token_hash=%s", (h(tok),))
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
def me(req: Request):
    u = current_user(req)
    return {"email": u["email"]} if u else {"email": None}

class NewWs(BaseModel):
    name: str = Field(min_length=2, max_length=60)

@app.get("/api/my/workspaces")
def my_workspaces(req: Request):
    u = need_user(req)
    return db.q("SELECT slug, name, created_at FROM workspaces WHERE owner_id=%s ORDER BY id", (u["id"],))

@app.post("/api/workspaces")
def create_ws(b: NewWs, req: Request):
    u = need_user(req)
    limit("ws:" + ip(req), 10, 3600)
    if db.q("SELECT count(*) AS n FROM workspaces", one=True)["n"] >= MAX_WORKSPACES:
        raise HTTPException(429, "Workspace limit reached on this free demo")
    if db.q("SELECT count(*) AS n FROM workspaces WHERE owner_id=%s", (u["id"],), one=True)["n"] >= MAX_WS_PER_USER:
        raise HTTPException(409, f"Free demo limit: {MAX_WS_PER_USER} workspaces per account")
    base = re.sub(r"[^a-z0-9]+", "-", b.name.lower()).strip("-")[:30] or "team"
    slug = f"{base}-{secrets.token_hex(2)}"
    db.q("INSERT INTO workspaces (slug,name,admin_hash,owner_id) VALUES (%s,%s,'',%s)", (slug, b.name.strip(), u["id"]))
    return {"slug": slug, "name": b.name.strip()}

@app.delete("/api/w/{slug}")
def delete_ws(slug, req: Request):
    w = admin(slug, req)
    db.q("DELETE FROM workspaces WHERE id=%s", (w["id"],))
    return {"ok": True}

@app.get("/api/w/{slug}")
def ws_info(slug, req: Request):
    w = ws_or_404(slug)
    n = db.q("SELECT count(*) AS n FROM documents WHERE workspace_id=%s", (w["id"],), one=True)["n"]
    u = current_user(req)
    return {"slug": slug, "name": w["name"], "documents": n, "is_demo": w["is_demo"], "threshold": agents.THRESHOLD,
            "can_manage": bool(u and w["owner_id"] == u["id"])}

class Chat(BaseModel):
    session_id: str = Field(min_length=6, max_length=64)
    question: str = Field(min_length=2, max_length=500)

def public_q(r):
    return {"id": r["id"], "question": r["question"], "answer": r["answer"], "confidence": r["confidence"], "status": r["status"],
            "human_reply": r["human_reply"], "sources": r["sources"], "trace": r["trace"], "verdict": r["verdict"],
            "escalation_reason": r["escalation_reason"], "created_at": r["created_at"].isoformat()}

@app.post("/api/w/{slug}/chat")
def chat(slug, b: Chat, req: Request):
    w = ws_or_404(slug)
    if not os.environ.get("OPENROUTER_API_KEY"): raise HTTPException(503, "LLM key not configured")
    limit("chat:" + ip(req), PER_IP_CHAT_HOUR, 3600)
    d = time.strftime("%Y-%m-%d")
    if _day["d"] != d: _day.update(d=d, n=0)
    if _day["n"] >= GLOBAL_CHAT_DAY: raise HTTPException(429, "Daily demo limit reached. Try again tomorrow.")
    _day["n"] += 1
    try:
        s = agents.run(w["id"], w["name"].replace(" (sample company)", ""), b.question.strip())
    except Exception as e:
        raise HTTPException(502, f"AI provider error: {type(e).__name__}")
    status = "auto_resolved" if s["decision"] == "respond" else "escalated"
    sources = [{"title": c["title"], "text": c["text"][:400]} for c in s["chunks"]] if status == "auto_resolved" else \
              [{"title": c["title"], "text": c["text"][:400]} for c in s["chunks"]]
    r = db.q("""INSERT INTO questions (workspace_id,session_id,question,answer,confidence,status,escalation_reason,sources,verdict,trace)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) RETURNING *""",
             (w["id"], b.session_id, b.question.strip(), None if (s.get("answer") or "").upper().startswith("INSUFFICIENT") else (s.get("answer") or None), s["confidence"], status, s.get("reason") or None,
              json.dumps(sources), json.dumps(s.get("verdict")), json.dumps(s["trace"])), one=True)
    out = public_q(r)
    if status == "escalated":
        out["answer"] = None  # never show an unverified draft to the customer
        out["draft_hidden"] = bool(s.get("answer")) and not s["answer"].upper().startswith("INSUFFICIENT")
    return out

@app.get("/api/w/{slug}/session/{sid}")
def session(slug, sid):
    w = ws_or_404(slug)
    rows = db.q("SELECT * FROM questions WHERE workspace_id=%s AND session_id=%s ORDER BY id", (w["id"], sid))
    out = []
    for r in rows:
        p = public_q(r)
        if r["status"] == "escalated": p["answer"] = None
        out.append(p)
    return out

# ---- admin ----
@app.get("/api/w/{slug}/admin/stats")
def stats(slug, req: Request):
    w = admin(slug, req, write=False)
    r = db.q("""SELECT count(*) AS total,
        count(*) FILTER (WHERE status='auto_resolved') AS auto,
        count(*) FILTER (WHERE status='escalated') AS open_escalations,
        count(*) FILTER (WHERE status='human_resolved') AS human,
        round(avg(confidence) FILTER (WHERE confidence IS NOT NULL))::int AS avg_conf
        FROM questions WHERE workspace_id=%s""", (w["id"],), one=True)
    r["docs"] = db.q("SELECT count(*) AS n FROM documents WHERE workspace_id=%s", (w["id"],), one=True)["n"]
    r["chunks"] = db.q("SELECT count(*) AS n FROM chunks WHERE workspace_id=%s", (w["id"],), one=True)["n"]
    r["auto_rate"] = round(100 * r["auto"] / r["total"]) if r["total"] else None
    return r

@app.get("/api/w/{slug}/admin/queue")
def queue(slug, req: Request, status: str = "escalated"):
    w = admin(slug, req, write=False)
    if status not in ("escalated", "human_resolved", "auto_resolved", "all"): raise HTTPException(400, "bad status")
    rows = db.q("SELECT * FROM questions WHERE workspace_id=%s AND (%s='all' OR status=%s) ORDER BY id DESC LIMIT 100", (w["id"], status, status))
    return [public_q(r) | {"session_id": r["session_id"]} for r in rows]

class Reply(BaseModel):
    reply: str = Field(min_length=2, max_length=2000)
    add_to_kb: bool = False

@app.post("/api/w/{slug}/admin/queue/{qid}/reply")
def reply(slug, qid: int, b: Reply, req: Request):
    w = admin(slug, req)
    r = db.q("SELECT * FROM questions WHERE id=%s AND workspace_id=%s", (qid, w["id"]), one=True)
    if not r: raise HTTPException(404, "Not found")
    if r["status"] != "escalated": raise HTTPException(409, "Already resolved")
    db.q("UPDATE questions SET status='human_resolved', human_reply=%s, resolved_at=now() WHERE id=%s", (b.reply.strip(), qid))
    if b.add_to_kb:
        n = db.q("SELECT count(*) AS n FROM documents WHERE workspace_id=%s", (w["id"],), one=True)["n"]
        if n < MAX_DOCS:
            db.add_document(w["id"], f"Human answer: {r['question'][:60]}", f"Q: {r['question']}\n\nA: {b.reply.strip()}", source="human")
    return {"ok": True}

class Doc(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    text: str = Field(min_length=20, max_length=MAX_DOC_CHARS)

@app.get("/api/w/{slug}/admin/docs")
def docs(slug, req: Request):
    w = admin(slug, req, write=False)
    rows = db.q("""SELECT d.id, d.title, d.source, d.created_at, (SELECT count(*) FROM chunks c WHERE c.document_id=d.id) AS chunks
                   FROM documents d WHERE d.workspace_id=%s ORDER BY d.id""", (w["id"],))
    return [r | {"created_at": r["created_at"].isoformat()} for r in rows]

@app.post("/api/w/{slug}/admin/docs")
def add_doc(slug, b: Doc, req: Request):
    w = admin(slug, req)
    limit("doc:" + ip(req), 30, 3600)
    if db.q("SELECT count(*) AS n FROM documents WHERE workspace_id=%s", (w["id"],), one=True)["n"] >= MAX_DOCS:
        raise HTTPException(409, f"Free demo limit: {MAX_DOCS} documents per workspace")
    did, n = db.add_document(w["id"], b.title.strip(), b.text)
    return {"id": did, "chunks": n}

@app.delete("/api/w/{slug}/admin/docs/{did}")
def del_doc(slug, did: int, req: Request):
    w = admin(slug, req)
    d = db.q("SELECT * FROM documents WHERE id=%s AND workspace_id=%s", (did, w["id"]), one=True)
    if not d: raise HTTPException(404, "Not found")
    if w["is_demo"] and d["source"] == "seed": raise HTTPException(403, "Sample documents in the demo workspace are protected")
    db.q("DELETE FROM documents WHERE id=%s", (did,))
    return {"ok": True}

# ---- frontend ----
DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
