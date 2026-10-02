import { useEffect, useState } from 'react'
import { api } from './api.js'
import Reasoning from './Reasoning.jsx'

const Stats = ({ title, s }) => s?.days ? (
  <div className="card"><h4>{title}</h4><small>{s.from} → {s.to}</small>
    <p>🌡️ {Math.round(s.temp_low_f)}–{Math.round(s.temp_high_f)}°F · 🌧️ {s.rain_total_in} in ({s.rainy_days} rainy days)<br />
      💧 humidity {s.humidity_min_pct}–{s.humidity_max_pct}% · ☀️ UV up to {Math.round(s.uv_max)} · 💨 {Math.round(s.wind_max_mph)} mph</p></div>) : null

// Weather tab: where is the plant, how has recent weather affected it, and what is coming this week.
export default function Weather({ plant, refresh, bump }) {
  const profile = (() => { try { return JSON.parse(plant.profile || '{}') } catch { return {} } })()
  const [place, setPlace] = useState(profile.location || ''); const [setting, setSetting] = useState(profile['indoor/outdoor'] || '')
  const [r, setR] = useState(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('')
  useEffect(() => { setPlace(profile.location || ''); setSetting(profile['indoor/outdoor'] || ''); setR(null); setErr('') }, [plant.id])
  const go = async () => {
    setBusy(true); setErr('')
    try { const out = await api.weather({ plant_id: plant.id, location: place, setting }); if (out.error || out.detail) setErr(out.error || out.detail); else { setR(out); refresh?.(); bump?.() } }
    catch { setErr('Could not reach the weather service.') } finally { setBusy(false) }
  }
  return (
    <>
      <h3>Weather at {plant.name}'s place</h3>
      <p>Tell me where the plant lives. I'll look at the last two weeks and the coming week.</p>
      <label>City (e.g. San Jose, California)<input value={place} onChange={(e) => setPlace(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && place.trim() && go()} /></label>
      <label>Where does it live?<select value={setting} onChange={(e) => setSetting(e.target.value)}>
        <option value="">Not sure</option><option value="indoor">Indoors</option><option value="outdoor">Outdoors</option></select></label>
      <button className="primary" disabled={busy || !place.trim()} onClick={go}>{busy ? 'Checking…' : 'Check weather effects'}</button>
      {err && <p>{err}</p>}
      {r?.assessment && <>
        <div className="card"><b>{r.place}</b><Reasoning text={r.assessment} /></div>
        {r.flags?.map((f, i) => <div key={i} className="card">⚠️ {f.when === 'past' ? 'Recently' : 'Coming up'}: {f.note}</div>)}
        <Stats title="Past two weeks" s={r.past} /><Stats title="Next 7 days" s={r.future} />
      </>}
    </>
  )
}
