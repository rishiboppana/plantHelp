import { useEffect, useState } from 'react'

// ---------- context window bar (also used by the Memory tab) ----------
const SEG = {
  skill: ['#2d6a4f', 'Skill instructions'], profile: ['#52b788', 'Plant profile'], findings: ['#f4a261', 'Image findings'],
  history: ['#95d5b2', 'History'], answers: ['#e9c46a', 'User answers'], rag: ['#457b9d', 'RAG chunks'],
  images: ['#8e7dbe', 'Photo'], graph: ['#e76f51', 'Memory graph'], reply: ['#b7e4c7', 'This reply'],
}
const n = (x) => Math.round(x || 0).toLocaleString()

export function ContextBar({ ctx }) {
  const segs = (ctx.segments || []).filter((s) => s.tokens > 0)
  const src = { provider: "the provider's published limit", model: "the model's smallest provider limit", env: 'set by PLANTLENS_CTX', assumed: 'assumed: the router did not list one' }[ctx.limit_source]
  return (
    <>
      <div className="ctxhead"><b>{n(ctx.used)}</b> / {n(ctx.limit)} tokens{ctx.exact === false ? ' (estimated)' : ''}</div>
      {src && <small title={ctx.model}>limit: {src}</small>}
      <div className="meter">{segs.map((s) => <div key={s.key} className="seg" title={`${(SEG[s.key] || [])[1] || s.label}: ${n(s.tokens)}`}
        style={{ width: `${(s.tokens / ctx.limit) * 100}%`, background: (SEG[s.key] || ['#999'])[0] }} />)}</div>
      <div className="legend">{segs.map((s) => <div key={s.key}><i style={{ background: (SEG[s.key] || ['#999'])[0] }} />{(SEG[s.key] || [])[1] || s.label}<b>{n(s.tokens)}</b></div>)}</div>
    </>
  )
}

// every model call of this conversation, newest last, each against the window (route / observe / verify / reply …)
export function CallList({ calls, limit }) {
  if (!calls?.length) return null
  return (
    <div className="legend calls">{calls.map((c, i) => <div key={i} title={`${c.model || ''}${c.exact ? '' : ' (estimated)'}`}>
      <i style={{ background: '#7b61c4', opacity: 0.35 + 0.65 * Math.min(1, (c.prompt + c.completion) / limit * 4) }} />
      <span>turn {c.turn} · {c.label}</span><b>{n(c.prompt)}→{n(c.completion)}</b></div>)}</div>
  )
}

// ---------- helpers ----------
const KIND = { turn: ['▶️', '#2d6a4f'], model: ['🤖', '#7b61c4'], retrieval: ['🔎', '#457b9d'], tool: ['🛠️', '#e07a5f'],
  context: ['🧠', '#52b788'], rag: ['📚', '#2a9d8f'], event: ['📅', '#c9a227'], wait: ['⏳', '#999'] }
const tokens = (s) => (s.kind === 'model' && s.attrs.total_tokens != null ? s.attrs.total_tokens : 0)
const ms = (v) => (v == null ? '…' : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`)
const HIDE = new Set(['segments', 'calls', 'chunks', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'source'])

function stats(spans) {
  const done = spans.filter((s) => s.kind !== 'event' && s.kind !== 'wait' || (s.kind === 'wait' && (s.dur_ms || 0) >= 50))
  const calls = spans.filter((s) => s.kind === 'model')
  const start = Math.min(...done.map((s) => s.start_ms)), end = Math.max(...done.map((s) => s.start_ms + (s.dur_ms || 0)))
  const slow = spans.filter((s) => ['model', 'retrieval', 'tool'].includes(s.kind) && s.dur_ms != null).sort((a, b) => b.dur_ms - a.dur_ms)[0]
  return { total: done.length ? end - start : 0, tokens: calls.reduce((a, s) => a + tokens(s), 0), calls: calls.length, slow }
}

function Stats({ spans }) {
  const st = stats(spans)
  return (
    <div className="tl-stats">
      <div><small>Total tokens</small><b>{n(st.tokens)}</b><span>{st.calls} model call{st.calls === 1 ? '' : 's'}</span></div>
      <div><small>Response time</small><b>{ms(st.total)}</b><span>first step to last</span></div>
      <div className="wide"><small>Slowest step</small><b>{st.slow ? ms(st.slow.dur_ms) : '–'}</b><span>{st.slow?.name || ''}</span></div>
    </div>
  )
}

// ---------- timeline ----------
function Timeline({ spans }) {
  const [open, setOpen] = useState(null)
  const rows = spans.filter((s) => !(s.kind === 'wait' && (s.dur_ms || 0) < 50) && s.kind !== 'rag' && !(s.kind === 'context' && 'segments' in s.attrs))
  const byId = Object.fromEntries(spans.map((s) => [s.id, s]))
  const depth = (s) => { let d = 0; for (let p = byId[s.parent]; p; p = byId[p.parent]) d++; return d }
  const sorted = [...rows].sort((a, b) => a.start_ms - b.start_ms)
  const t0 = Math.min(...sorted.map((s) => s.start_ms)), t1 = Math.max(...sorted.map((s) => s.start_ms + (s.dur_ms || 0)), t0 + 1)
  const slowest = stats(spans).slow
  return (
    <div className="tl">
      {sorted.map((s) => {
        const [icon, color] = KIND[s.kind] || ['•', '#999']
        const running = s.status === 'running'
        const extra = Object.entries(s.attrs).filter(([k]) => !HIDE.has(k))
        return (
          <div key={s.id} className={`tl-row ${s.status} ${slowest?.id === s.id ? 'slow' : ''}`} style={{ paddingLeft: depth(s) * 12 }} onClick={() => setOpen(open === s.id ? null : s.id)}>
            <div className="tl-line">
              <span className="tl-ic">{icon}</span>
              <span className="tl-name">{s.name}</span>
              {s.kind === 'model' && s.attrs.total_tokens != null && <span className="tl-tok" title={`${s.attrs.source === 'provider' ? 'reported by the provider' : 'estimated'}`}>{n(s.attrs.prompt_tokens)}→{n(s.attrs.completion_tokens)} tok</span>}
              <span className="tl-ms">{running ? <i className="spin" /> : ms(s.dur_ms)}</span>
            </div>
            <div className="tl-track"><div className={running ? 'tl-bar run' : 'tl-bar'} style={{ left: `${((s.start_ms - t0) / (t1 - t0)) * 100}%`, width: `${Math.max(1.5, ((running ? t1 - s.start_ms : s.dur_ms || 0) / (t1 - t0)) * 100)}%`, background: s.status === 'error' ? '#c0392b' : color }} /></div>
            {open === s.id && <pre className="tl-attrs">{extra.length ? extra.map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join('\n') : 'no details'}</pre>}
          </div>
        )
      })}
    </div>
  )
}

// ---------- RAG evidence ----------
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u } }

function Rag({ spans }) {
  const ev = spans.filter((s) => s.kind === 'rag')
  const e = ev.find((s) => s.attrs.source === 'reply') || ev[ev.length - 1]
  const searched = spans.filter((s) => s.kind === 'retrieval')
  if (!e) return <p>{searched.length ? 'The knowledge base was searched but nothing relevant came back.' : 'No knowledge-base lookup in this turn.'}</p>
  const a = e.attrs
  const maxScore = Math.max(...a.chunks.map((c) => c.score), 1e-9)
  return (
    <>
      <div className="chips">
        <span className="chip">coverage: {a.coverage}</span>
        {(a.filters_relaxed || []).length > 0 && <span className="chip" title="filters dropped to find enough records">relaxed: {a.filters_relaxed.join(', ')}</span>}
        <span className="chip">{a.source === 'reply' ? 'from the chat answer' : 'from the photo analysis'}</span>
      </div>
      {a.chunks.map((c) => (
        <div key={c.record_id} className={`rag ${c.cited ? 'used' : ''}`}>
          <div className="rag-head"><b>#{c.rank} {c.cause}</b>
            <span className={`badge ${c.fallback ? 'warn' : c.cited ? 'ok' : ''}`}>{c.fallback ? 'added as fallback' : c.cited ? 'used in answer' : 'sent, not used'}</span></div>
          <div className="rag-bars">
            <label>similarity <b>{c.cosine}</b></label><div className="rag-track"><div style={{ width: `${Math.max(0, c.cosine) * 100}%` }} /></div>
            <label>fused score <b>{c.score}</b></label><div className="rag-track alt"><div style={{ width: `${(c.score / maxScore) * 100}%` }} /></div>
          </div>
          <div className="chips">
            {c.keyword_hit && <span className="chip">keyword hit{c.kw_rank ? ` #${c.kw_rank}` : ''}</span>}
            {c.vec_rank && <span className="chip">vector #{c.vec_rank}</span>}
            {c.symptom_overlap.map((x) => <span key={x} className="chip">{x}</span>)}
          </div>
          <small><a href={c.source_url} target="_blank" rel="noreferrer">{host(c.source_url)}</a> · {c.record_id}</small>
          <details><summary>Summary</summary><div>{c.summary}</div></details>
        </div>
      ))}
    </>
  )
}

// ---------- the Trace tab ----------
export function TracePanel({ tr, busy, onRefresh, version }) {
  useEffect(() => { if (tr?.id && !busy) onRefresh() }, [version])   // event actions append to the trace on the server
  const spans = tr?.spans || []
  const ctxSpan = [...spans].reverse().find((s) => s.kind === 'context' && 'segments' in s.attrs)
  if (!spans.length) return <><h3>Trace</h3><p>Send a message or photo and every step I take shows up here, live.</p></>
  return (
    <>
      <div className="tl-title"><h3>What just happened</h3>{!busy && <button onClick={onRefresh} title="Reload">↻</button>}</div>
      <Stats spans={spans} />
      <h4 className="tl-h">Timeline</h4>
      <Timeline spans={spans} />
      <h4 className="tl-h">Context window</h4>
      {ctxSpan ? <ContextBar ctx={{ ...ctxSpan.attrs }} /> : <p>Waiting for the prompt to be built…</p>}
      <h4 className="tl-h">RAG evidence</h4>
      <Rag spans={spans} />
    </>
  )
}
