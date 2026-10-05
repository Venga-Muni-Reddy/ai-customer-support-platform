import React, { useEffect, useRef, useState } from 'react'

const api = async (path, opts = {}) => {
  const r = await fetch('/api' + path, { ...opts, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Request failed (' + r.status + ')')
  return j
}
const useHash = () => {
  const [h, setH] = useState(location.hash || '#/')
  useEffect(() => { const f = () => setH(location.hash || '#/'); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  return h
}
const sid = () => { let s = localStorage.getItem('sp_sid'); if (!s) { s = 's' + Math.random().toString(36).slice(2, 12); localStorage.setItem('sp_sid', s) } return s }

const AuthCtx = React.createContext(null)

export default function App() {
  const h = useHash()
  const [user, setUser] = useState(undefined)
  useEffect(() => { api('/auth/me').then(r => setUser(r.email)).catch(() => setUser(null)) }, [])
  const logout = async () => { await api('/auth/logout', { method: 'POST' }).catch(() => {}); setUser(null); location.hash = '#/' }
  const m = h.match(/^#\/w\/([^/]+)(\/admin)?/)
  let page
  if (m) page = m[2] ? <Admin slug={m[1]} /> : <Chat slug={m[1]} />
  else if (h === '#/login' || h === '#/signup') page = <AuthForm mode={h === '#/signup' ? 'signup' : 'login'} />
  else if (h === '#/workspaces') page = <Workspaces />
  else page = <Home />
  return (
    <AuthCtx.Provider value={{ user, setUser }}>
      <header className="top"><a href="#/" className="logo">SupportPilot</a>
        <nav><a href="#/w/demo">Demo chat</a><a href="#/w/demo/admin">Demo dashboard</a>
          {user === undefined ? null : user
            ? <><a href="#/workspaces">My workspaces</a><span className="muted who">{user}</span><button className="link" onClick={logout}>Log out</button></>
            : <><a href="#/login">Log in</a><a className="btn sm" href="#/signup">Sign up</a></>}
        </nav></header>
      {page}
    </AuthCtx.Provider>
  )
}

function AuthForm({ mode }) {
  const { user, setUser } = React.useContext(AuthCtx)
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { if (user) location.hash = '#/workspaces' }, [user])
  const go = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { const r = await api('/auth/' + mode, { method: 'POST', body: JSON.stringify({ email, password: pw }) }); setUser(r.email); location.hash = '#/workspaces' }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const su = mode === 'signup'
  return (
    <main className="wrap narrow"><h2>{su ? 'Create your account' : 'Log in'}</h2>
      <form onSubmit={go} className="card">
        <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email" required autoComplete="email" />
        <input type="password" value={pw} onChange={e => setPw(e.target.value)} placeholder={su ? 'Password (8 to 72 characters)' : 'Password'} required minLength={su ? 8 : 1} maxLength={72} autoComplete={su ? 'new-password' : 'current-password'} />
        <button className="btn" disabled={busy}>{busy ? 'Please wait...' : su ? 'Sign up' : 'Log in'}</button>
        {err && <p className="err">{err}</p>}
      </form>
      <p className="muted">{su ? <>Already have an account? <a href="#/login">Log in</a></> : <>No account yet? <a href="#/signup">Sign up</a></>}. Passwords are hashed with bcrypt. You only need an account to create your own workspace; the demo needs none.</p>
    </main>
  )
}

function Workspaces() {
  const { user } = React.useContext(AuthCtx)
  const [list, setList] = useState(null); const [name, setName] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const load = () => api('/my/workspaces').then(setList).catch(e => setErr(e.message))
  useEffect(() => { if (user) load() }, [user])
  if (user === undefined) return <main className="wrap"><p>Loading...</p></main>
  if (!user) return <main className="wrap narrow"><h2>My workspaces</h2><p>Please <a href="#/login">log in</a> or <a href="#/signup">sign up</a> to create and manage your own workspaces.</p></main>
  const create = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { const r = await api('/workspaces', { method: 'POST', body: JSON.stringify({ name }) }); location.hash = '#/w/' + r.slug + '/admin' }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const del = async w => { if (!confirm('Delete workspace "' + w.name + '" and all its data?')) return; try { await api('/w/' + w.slug, { method: 'DELETE' }); load() } catch (x) { setErr(x.message) } }
  return (
    <main className="wrap narrow"><h2>My workspaces</h2>
      <p className="muted">Signed in as {user}. Only you can open the dashboard of your workspaces.</p>
      {list && list.length === 0 && <p className="muted">No workspaces yet. Create your first one below.</p>}
      {list && list.map(w => <div className="card row2" key={w.slug}><span><b>{w.name}</b></span>
        <span><a className="btn sm" href={'#/w/' + w.slug + '/admin'}>Dashboard</a> <a className="btn ghost sm" href={'#/w/' + w.slug}>Customer chat</a> <button className="link" onClick={() => del(w)}>Delete</button></span></div>)}
      <form onSubmit={create} className="row"><input value={name} onChange={e => setName(e.target.value)} placeholder="Your business name" required minLength={2} maxLength={60} /><button className="btn" disabled={busy}>{busy ? 'Creating...' : 'Create workspace'}</button></form>
      {err && <p className="err">{err}</p>}
      <p className="muted">Free demo limits: 3 workspaces per account, 12 documents per workspace.</p>
    </main>
  )
}


function Home() {
  const { user } = React.useContext(AuthCtx)
  return (
    <main className="wrap">
      <section className="hero">
        <h1>AI customer support that knows when <em>not</em> to answer</h1>
        <p>Upload your help docs. A team of LangGraph agents answers customer questions from them, a second agent fact-checks every answer against the sources, and anything it is not sure about goes to a human queue instead of reaching the customer.</p>
        <div className="cta"><a className="btn" href="#/w/demo">Try the live demo chat</a><a className="btn ghost" href="#/w/demo/admin">View the demo dashboard</a></div>
        <p className="muted">No signup needed for the demo.</p>
      </section>
      <section className="grid3">
        <div className="card"><h3>1. Retrieve</h3><p>PostgreSQL full-text search finds the relevant passages in your documents.</p></div>
        <div className="card"><h3>2. Answer + verify</h3><p>One agent drafts an answer with citations. A separate verifier scores it against the sources.</p></div>
        <div className="card"><h3>3. Respond or escalate</h3><p>High confidence replies instantly. Low confidence goes to a human queue, and the human answer can be saved back to the knowledge base.</p></div>
      </section>
      <section className="card">
        <h2>Create your own workspace</h2>
        <p>Sign up with email and password, then create a workspace, add your docs and resolve escalations. Each workspace is private to your account.</p>
        <div className="cta">{user ? <a className="btn" href="#/workspaces">Go to my workspaces</a> : <><a className="btn" href="#/signup">Sign up</a><a className="btn ghost" href="#/login">Log in</a></>}</div>
        <p className="muted">Free demo limits: 12 documents per workspace, rate-limited chat. Retrieval is keyword-based full-text search (no vector embeddings).</p>
      </section>
    </main>
  )
}

function Badge({ q }) {
  if (q.status === 'auto_resolved') return <span className="badge ok">Auto-answered - confidence {q.confidence}</span>
  if (q.status === 'human_resolved') return <span className="badge hum">Answered by a human</span>
  return <span className="badge esc">Escalated to a human</span>
}

function Chat({ slug }) {
  const [info, setInfo] = useState(null); const [msgs, setMsgs] = useState([]); const [text, setText] = useState('')
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const end = useRef()
  const load = async () => { try { setMsgs(await api(`/w/${slug}/session/${sid()}`)) } catch {} }
  useEffect(() => { api('/w/' + slug).then(setInfo).catch(e => setErr(e.message)); load() }, [slug])
  useEffect(() => { const t = setInterval(() => { if (msgs.some(m => m.status === 'escalated')) load() }, 6000); return () => clearInterval(t) }, [msgs, slug])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy])
  const send = async e => {
    e.preventDefault(); const q = text.trim(); if (!q || busy) return
    setBusy(true); setErr(''); setText('')
    setMsgs(m => [...m, { id: 'tmp', question: q, status: 'pending' }])
    try { await api(`/w/${slug}/chat`, { method: 'POST', body: JSON.stringify({ session_id: sid(), question: q }) }); await load() }
    catch (x) { setErr(x.message); await load() } finally { setBusy(false) }
  }
  if (err && !info) return <main className="wrap"><p className="err">{err}</p></main>
  return (
    <main className="wrap narrow">
      <h2>{info ? info.name : '...'} - support</h2>
      {info?.is_demo && <p className="muted">Sample company with fictional policies (shipping, returns, warranty, tent care, support hours). Try: "How much is express shipping?", "Can I return a sleeping bag I opened?", then something it can't know like "Do you sell kayaks?" to see escalation.</p>}
      <div className="chat">
        {msgs.length === 0 && <p className="muted">Ask a question to begin.</p>}
        {msgs.map(m => (
          <div key={m.id}>
            <div className="bub me">{m.question}</div>
            {m.status === 'pending' ? <div className="bub bot">Agents working: retrieve, answer, verify...</div> : (
              <div className="bub bot">
                <Badge q={m} />
                {m.status === 'auto_resolved' && <p>{m.answer}</p>}
                {m.status === 'escalated' && <p>I'm not confident I can answer this correctly from our documentation, so I've passed it to our support team. Keep this page open - their reply will appear here.</p>}
                {m.status === 'human_resolved' && <p>{m.human_reply}</p>}
                <Details m={m} />
              </div>)}
          </div>))}
        <div ref={end} />
      </div>
      {err && <p className="err">{err}</p>}
      <form onSubmit={send} className="row"><input value={text} onChange={e => setText(e.target.value)} placeholder="Type your question" maxLength={500} /><button className="btn" disabled={busy}>Send</button></form>
      <p className="muted">First reply may take up to a minute if the free server was asleep. {info?.is_demo ? <a href={`#/w/${slug}/admin`}>View demo dashboard</a> : info?.can_manage && <a href={`#/w/${slug}/admin`}>Open dashboard</a>}</p>
    </main>
  )
}

function Details({ m }) {
  const [open, setOpen] = useState(false)
  if (!m.trace?.length) return null
  return (
    <div>
      <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'} how the agents decided</button>
      {open && (
        <div className="det">
          <ol>{m.trace.map((t, i) => <li key={i}><b>{t.agent}</b>: {t.detail}{t.ms ? ` (${t.ms} ms)` : ''}</li>)}</ol>
          {m.verdict && m.verdict.unsupported_claims?.length > 0 && <p><b>Verifier flagged:</b> {m.verdict.unsupported_claims.join('; ')}</p>}
          {m.escalation_reason && <p><b>Escalation reason:</b> {m.escalation_reason}</p>}
          {m.sources?.length > 0 && <div><b>Sources:</b>{m.sources.map((s, i) => <blockquote key={i}>[{i + 1}] {s.title}: {s.text}</blockquote>)}</div>}
        </div>)}
    </div>
  )
}

function Admin({ slug }) {
  const { user } = React.useContext(AuthCtx)
  const [info, setInfo] = useState(null); const [tab, setTab] = useState('queue'); const [err, setErr] = useState('')
  const [stats, setStats] = useState(null)
  const refresh = async () => { try { setStats(await api(`/w/${slug}/admin/stats`)); setErr('') } catch (x) { setErr(x.message); setStats(null) } }
  useEffect(() => { api('/w/' + slug).then(setInfo).catch(e => setErr(e.message)) }, [slug])
  useEffect(() => { if (user !== undefined) refresh() }, [slug, user])
  if (user === undefined) return <main className="wrap"><p>Loading...</p></main>
  if (!stats) return (
    <main className="wrap narrow"><h2>Dashboard - {slug}</h2>
      {!user && slug !== 'demo' ? <p>Please <a href="#/login">log in</a> to open this dashboard. Only the workspace owner can see it.</p> : err && <p className="err">{err}</p>}</main>)
  const ro = !!info?.is_demo
  return (
    <main className="wrap">
      <h2>Dashboard - {info ? info.name : slug}</h2>
      {ro && <p className="muted banner">Read-only demo dashboard with sample data. <a href="#/signup">Sign up</a> to create your own workspace, add documents and reply to escalations.</p>}
      <div className="stats">
        <Stat l="Questions" v={stats.total} /><Stat l="Auto-resolved" v={stats.auto} /><Stat l="Open escalations" v={stats.open_escalations} /><Stat l="Human-resolved" v={stats.human} />
        <Stat l="Auto rate" v={stats.auto_rate == null ? '-' : stats.auto_rate + '%'} /><Stat l="Avg confidence" v={stats.avg_conf ?? '-'} /><Stat l="Documents" v={stats.docs} />
      </div>
      <div className="tabs">{['queue', 'history', 'knowledge'].map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t === 'queue' ? 'Escalation queue' : t === 'history' ? 'All conversations' : 'Knowledge base'}</button>)}</div>
      {tab === 'queue' && <Queue slug={slug} status="escalated" onChange={refresh} reply={!ro} />}
      {tab === 'history' && <Queue slug={slug} status="all" onChange={refresh} />}
      {tab === 'knowledge' && <Docs slug={slug} onChange={refresh} ro={ro} />}
    </main>
  )
}
const Stat = ({ l, v }) => <div className="stat"><div className="n">{v}</div><div>{l}</div></div>

function Queue({ slug, status, onChange, reply }) {
  const [rows, setRows] = useState(null); const [txt, setTxt] = useState({}); const [kb, setKb] = useState({}); const [err, setErr] = useState('')
  const load = () => api(`/w/${slug}/admin/queue?status=${status}`).then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [status])
  const send = async id => {
    try { await api(`/w/${slug}/admin/queue/${id}/reply`, { method: 'POST', body: JSON.stringify({ reply: txt[id] || '', add_to_kb: !!kb[id] }) }); await load(); onChange() }
    catch (x) { setErr(x.message) }
  }
  if (!rows) return <p>Loading...</p>
  return (
    <div>
      {err && <p className="err">{err}</p>}
      {rows.length === 0 && <p className="muted">{reply ? 'No escalations. Ask the demo chat something it cannot know to create one.' : 'No conversations yet.'}</p>}
      {rows.map(r => (
        <div className="card" key={r.id}>
          <div className="qhead"><b>{r.question}</b><Badge q={r} /></div>
          {r.escalation_reason && <p className="muted">Why: {r.escalation_reason}</p>}
          {r.answer && <p><b>{r.status === 'escalated' ? 'Draft (hidden from customer)' : 'Answer'}:</b> {r.answer}</p>}
          {r.human_reply && <p><b>Human reply:</b> {r.human_reply}</p>}
          <Details m={r} />
          {reply && r.status === 'escalated' && (
            <div>
              <textarea rows={3} placeholder="Write the reply the customer will see" value={txt[r.id] || ''} onChange={e => setTxt({ ...txt, [r.id]: e.target.value })} />
              <label className="chk"><input type="checkbox" checked={!!kb[r.id]} onChange={e => setKb({ ...kb, [r.id]: e.target.checked })} /> Also save Q&amp;A to the knowledge base</label>
              <button className="btn" onClick={() => send(r.id)}>Send reply</button>
            </div>)}
        </div>))}
    </div>
  )
}

function Docs({ slug, onChange, ro }) {
  const [docs, setDocs] = useState([]); const [t, setT] = useState(''); const [x, setX] = useState(''); const [err, setErr] = useState('')
  const load = () => api(`/w/${slug}/admin/docs`).then(setDocs).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])
  const add = async e => { e.preventDefault(); setErr(''); try { await api(`/w/${slug}/admin/docs`, { method: 'POST', body: JSON.stringify({ title: t, text: x }) }); setT(''); setX(''); await load(); onChange() } catch (z) { setErr(z.message) } }
  const del = async id => { setErr(''); try { await api(`/w/${slug}/admin/docs/${id}`, { method: 'DELETE' }); await load(); onChange() } catch (z) { setErr(z.message) } }
  return (
    <div>
      {!ro && <div className="card"><h3>Add a document</h3>
        <form onSubmit={add}><input value={t} onChange={e => setT(e.target.value)} placeholder="Title (e.g. Refund policy)" required minLength={2} />
          <textarea rows={6} value={x} onChange={e => setX(e.target.value)} placeholder="Paste FAQ or help-center text (max 20,000 characters). Separate topics with blank lines." required minLength={20} />
          <button className="btn">Add to knowledge base</button></form></div>}
      {err && <p className="err">{err}</p>}
      {docs.map(d => <div className="card row2" key={d.id}><span><b>{d.title}</b> <span className="muted">{d.chunks} chunk(s) - {d.source}</span></span>{!ro && <button className="link" onClick={() => del(d.id)}>Delete</button>}</div>)}
    </div>
  )
}
