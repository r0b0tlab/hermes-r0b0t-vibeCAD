import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// The media slot has no transcript position. Do not infer it from mount or URL
// completion order: virtualized history can remount older cards at any time.
const sheets = sdk.atom({})
const pending = new Map()
const TOOL = 'vibecad_generate_preview_renders'
const VIEW_ORDER = ['iso', 'top', 'front', 'right', 'bottom']

function asObject(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value
  if (typeof value === 'string') {
    try { return asObject(JSON.parse(value)) } catch { return null }
  }
  return null
}

function viewName(file, result) {
  const renders = asObject(result)?.renders
  if (renders && typeof renders === 'object') {
    for (const name of Object.keys(renders)) if (renders[name] === file.path) return name
  }
  return (file.name || '').replace(/^preview_/, '').replace(/\.png$/i, '') || 'drawing'
}

function orderedNames(views) {
  return Object.keys(views).sort((a, b) => {
    const ia = VIEW_ORDER.indexOf(a.toLowerCase())
    const ib = VIEW_ORDER.indexOf(b.toLowerCase())
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
  })
}

function setSession(sessionId, change) {
  const all = sheets.get()
  const previous = Object.hasOwn(all, sessionId) ? all[sessionId] : { candidates: {}, selected: null }
  sheets.set({ ...all, [sessionId]: change(previous) })
}

// session.history is a compact projection: tool rows expose name and call ID,
// but not our result. A reused ID is ambiguous and is deliberately excluded.
async function rankSheets(sessionId, runtimeId) {
  const ticket = (pending.get(sessionId) || 0) + 1
  pending.set(sessionId, ticket)
  try {
    const response = await sdk.host.request('session.history', { session_id: runtimeId || sessionId })
    if (pending.get(sessionId) !== ticket) return
    if (!Array.isArray(response?.messages)) throw new Error('Invalid session history')
    const rows = response.messages.filter(row => row?.role === 'tool' && row.name === TOOL && typeof row.tool_call_id === 'string' && row.tool_call_id)
    const counts = new Map()
    for (const row of rows) counts.set(row.tool_call_id, (counts.get(row.tool_call_id) || 0) + 1)
    setSession(sessionId, state => {
      let selected = null
      for (const row of rows) {
        if (Object.hasOwn(state.candidates, row.tool_call_id)) selected = counts.get(row.tool_call_id) === 1 ? row.tool_call_id : null
      }
      return { ...state, selected }
    })
  } catch {
    // No chronology means no truthful latest sheet; the inline card still works.
    if (pending.get(sessionId) === ticket) setSession(sessionId, state => ({ ...state, selected: null }))
  }
}

function recordView(sessionId, callId, signature, label, url) {
  setSession(sessionId, state => {
    const candidate = Object.hasOwn(state.candidates, callId) ? state.candidates[callId] : null
    // Same call ID with different results is ambiguous, never merge them.
    if (candidate && candidate.signature !== signature) {
      return { ...state, candidates: { ...state.candidates, [callId]: { ambiguous: true } }, selected: state.selected === callId ? null : state.selected }
    }
    if (candidate?.ambiguous) return state
    const views = { ...candidate?.views }
    if (url) views[label] = { url }
    return { ...state, candidates: { ...state.candidates, [callId]: { signature, views } } }
  })
  const focusedStored = sdk.host.state.focusedStoredSessionId.get()
  const focusedRuntime = sdk.host.state.focusedSessionId.get()
  rankSheets(sessionId, sessionId === (focusedStored || focusedRuntime) ? focusedRuntime : null)
}

function removeView(sessionId, callId, label, url) {
  if (!sessionId || !callId) return
  setSession(sessionId, state => {
    const candidate = Object.hasOwn(state.candidates, callId) ? state.candidates[callId] : null
    if (!candidate?.views || candidate.views[label]?.url !== url) return state
    const views = { ...candidate.views }
    delete views[label]
    return { ...state, candidates: { ...state.candidates, [callId]: { ...candidate, views } } }
  })
}

function DrawingCard({ file, result, fallback, sessionId, toolCallId }) {
  const [loaded, setLoaded] = useState(null)
  const path = file?.path
  const label = file ? viewName(file, result) : 'drawing'
  const renders = asObject(result)?.renders
  // A result's complete map identifies its revision even when call IDs repeat.
  const signature = renders && typeof renders === 'object' ? JSON.stringify(Object.entries(renders).sort(([a], [b]) => a.localeCompare(b))) : null
  const key = JSON.stringify([sessionId, toolCallId, path, label, signature])
  useEffect(() => {
    if (file?.kind !== 'image' || typeof file.resolveUrl !== 'function' || !path) return undefined
    let live = true
    if (sessionId && toolCallId && signature && renders[label] === path) recordView(sessionId, toolCallId, signature, label, null)
    Promise.resolve().then(() => file.resolveUrl()).then(url => {
      if (!live || typeof url !== 'string' || !url) return
      setLoaded({ key, url })
      if (sessionId && toolCallId && signature && renders[label] === path) recordView(sessionId, toolCallId, signature, label, url)
    }).catch(() => {})
    return () => { live = false }
  }, [path, key, file?.kind])
  if (!file || file.kind !== 'image' || loaded?.key !== key || !loaded.url) return fallback
  return jsxs('figure', {
    style: { margin: 0, maxWidth: 420, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 8, overflow: 'hidden' },
    children: [
      jsx('img', { alt: `${label} drawing`, src: loaded.url, onError: () => { removeView(sessionId, toolCallId, label, loaded.url); setLoaded(null) }, style: { display: 'block', width: '100%', height: 'auto' } }),
      jsx('figcaption', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.06em', padding: '6px 8px' }, children: String(label).toUpperCase() }),
    ],
  })
}

function DrawingPane() {
  // Renderer sessionId is stored id when available, otherwise runtime id.
  const stored = sdk.useValue(sdk.host.state.focusedStoredSessionId)
  const runtime = sdk.useValue(sdk.host.state.focusedSessionId)
  const all = sdk.useValue(sheets)
  const id = stored || runtime
  useEffect(() => {
    if (id) rankSheets(id, runtime)
  }, [id, runtime])
  const session = id && Object.hasOwn(all, id) ? all[id] : null
  const candidate = session?.selected && Object.hasOwn(session.candidates, session.selected) ? session.candidates[session.selected] : null
  const views = candidate && !candidate.ambiguous ? candidate.views : {}
  const names = orderedNames(views || {})
  if (!names.length) return jsx(sdk.EmptyState, {
    title: 'No drawing available',
    description: 'Emit the preview media in this chat and open its transcript. The pane shows views from the latest observed sheet when its order can be verified.',
  })
  return jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 12, padding: 12 },
    children: names.map(name => jsxs('figure', {
      key: name, style: { margin: 0 },
      children: [
        jsx('figcaption', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.06em' }, children: name.toUpperCase() }),
        jsx('img', { alt: `${name} drawing`, src: views[name].url, onError: () => removeView(id, session.selected, name, views[name].url), style: { display: 'block', width: '100%', height: 'auto' } }),
      ],
    })),
  })
}

export default {
  id: 'hermes-r0b0t-vibeCAD',
  name: 'vibeCAD drawings',
  register(ctx) {
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') ctx.register({
      id: 'preview-drawings', area: sdk.TOOL_MEDIA_RENDERER_AREA,
      data: { tools: [TOOL], render: props => jsx(DrawingCard, props) },
    })
    ctx.register({ id: 'drawing-pane', area: 'panes', title: 'vibeCAD', data: { placement: 'right', width: '300px' }, render: () => jsx(DrawingPane, {}) })
  },
}
