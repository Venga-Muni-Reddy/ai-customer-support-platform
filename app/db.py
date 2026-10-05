import os, re
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

_pool = None

def pool():
    global _pool
    if _pool is None:
        url = os.environ["DATABASE_URL"]
        _pool = ConnectionPool(url, min_size=1, max_size=5, kwargs={"row_factory": dict_row, "autocommit": True}, open=True)
    return _pool

def init():
    sql = open(os.path.join(os.path.dirname(__file__), "schema.sql")).read()
    with pool().connection() as c:
        c.execute(sql)

def q(sql, params=(), one=False):
    with pool().connection() as c:
        cur = c.execute(sql, params)
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()

STOP = set("a an the is are was were be been am do does did to of in on at for with and or but if it its i my me we our you your can could would should will how what when where why which who whom this that these those there here about as by from not no yes please any have has had get got just".split())

def tsquery_or(text):
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w); out.append(w)
    return " | ".join(out[:20])

def search_chunks(ws_id, question, k=4):
    tq = tsquery_or(question)
    if not tq:
        return []
    return q(
        """SELECT c.id, c.content, d.title, ts_rank_cd(c.tsv, to_tsquery('english', %s)) AS score
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE c.workspace_id = %s AND c.tsv @@ to_tsquery('english', %s)
           ORDER BY score DESC LIMIT %s""",
        (tq, ws_id, tq, k))

def chunk_text(text, target=700):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r", "")) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > target * 1.5:
            sents = re.split(r"(?<=[.!?])\s+", p)
        else:
            sents = [p]
        for s in sents:
            if cur and len(cur) + len(s) > target:
                chunks.append(cur.strip()); cur = ""
            cur += (" " if cur and not cur.endswith("\n") else "") + s + "\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks

def add_document(ws_id, title, text, source="upload"):
    doc = q("INSERT INTO documents (workspace_id, title, source) VALUES (%s,%s,%s) RETURNING id", (ws_id, title, source), one=True)
    parts = chunk_text(text)
    with pool().connection() as c:
        for i, ch in enumerate(parts):
            c.execute("INSERT INTO chunks (document_id, workspace_id, idx, content) VALUES (%s,%s,%s,%s)", (doc["id"], ws_id, i, ch))
    return doc["id"], len(parts)
