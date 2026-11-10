import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// The media slot has no transcript position. Do not infer it from mount or URL
// completion order: virtualized history can remount older cards at any time.
const sheets = sdk.atom({})
const pending = new Map()
const TOOL = 'vibecad_generate_preview_renders'
const BRIDGE = 'tool_call'
const VIEW_ORDER = ['iso', 'top', 'front', 'back', 'right', 'bottom']

// A deferred tool call is stored as the "tool_call" bridge: the row's own name
// is the bridge, and the tool that actually ran is named in args.calls[0].
// Upstream unwraps this the same way when it hands a tool call to a renderer
// (effectiveToolCall), so the pane must unwrap it too or it never sees its own
// tool. A batch of several calls stays the bridge: no plugin owns it.
function ranTool(row) {
  const name = row?.name
  if (name !== BRIDGE) return name
  const args = row?.args
  if (!args || typeof args !== 'object') return name
  let calls = args.calls
  if (calls === undefined || calls === null) {
    calls = typeof args.name === 'string' && args.name.trim() ? [{ arguments: args.arguments, name: args.name }] : null
  }
  if (typeof calls === 'string') {
    try { calls = JSON.parse(calls) } catch { return name }
  }
  if (calls && typeof calls === 'object' && !Array.isArray(calls)) calls = [calls]
  if (!Array.isArray(calls) || calls.length !== 1) return name
  const entry = calls[0]
  const inner = typeof entry?.name === 'string' ? entry.name.trim() : ''
  return inner && inner !== BRIDGE ? inner : name
}

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

function displayName(name) {
  return String(name).replace(/^(.+?)_detail_/, '$1 · detail: ').replaceAll('_', ' ')
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
    const rows = response.messages.filter(row => row?.role === 'tool' && ranTool(row) === TOOL && typeof row.tool_call_id === 'string' && row.tool_call_id)
    const counts = new Map()
    for (const row of rows) counts.set(row.tool_call_id, (counts.get(row.tool_call_id) || 0) + 1)
    setSession(sessionId, state => {
      let selected = null
      for (const row of rows) {
        if (Object.hasOwn(state.candidates, row.tool_call_id)) selected = counts.get(row.tool_call_id) === 1 ? row.tool_call_id : null
      }
      return { ...state, selected, historyError: false }
    })
  } catch {
    // No chronology means no truthful latest sheet; the inline card still works.
    if (pending.get(sessionId) === ticket) setSession(sessionId, state => ({ ...state, selected: null, historyError: true }))
  }
}

// Only data returned by the tool is presented as model provenance.
function sheetMetadata(result) {
  const data = asObject(result) || {}
  const path = typeof data.step_file === 'string' ? data.step_file : typeof data.mesh_file === 'string' ? data.mesh_file : null
  const sourceHash = data.source_sha256 ?? data.source_step_sha256
  const hash = typeof sourceHash === 'string' && /^[a-f0-9]{64}$/i.test(sourceHash) ? sourceHash : null
  const metadata = asObject(data.render_metadata) || {}
  return { path, type: path ? (data.step_file === path ? 'STEP' : 'STL') : null, hash, metadata }
}

function recordView(sessionId, callId, signature, label, url, metadata, total, status = 'loading') {
  setSession(sessionId, state => {
    const candidate = Object.hasOwn(state.candidates, callId) ? state.candidates[callId] : null
    // Same call ID with different results is ambiguous, never merge them.
    if (candidate && candidate.signature !== signature) {
      return { ...state, candidates: { ...state.candidates, [callId]: { ambiguous: true } }, selected: state.selected === callId ? null : state.selected }
    }
    if (candidate?.ambiguous) return state
    const views = { ...candidate?.views }
    if (url) views[label] = { url, status: 'ready' }
    else if (!views[label]?.url) views[label] = { status }
    return { ...state, candidates: { ...state.candidates, [callId]: { signature, views, metadata, total } } }
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
    views[label] = { status: 'error' }
    return { ...state, candidates: { ...state.candidates, [callId]: { ...candidate, views } } }
  })
}

function DrawingCard({ file, result, fallback, sessionId, toolCallId }) {
  const [loaded, setLoaded] = useState(null)
  const path = file?.path
  const label = file ? viewName(file, result) : 'drawing'
  const renders = asObject(asObject(result)?.renders)
  const metadata = sheetMetadata(result)
  // Bind context to this revision as well as its image paths.
  const signature = renders ? JSON.stringify([Object.entries(renders).sort(([a], [b]) => a.localeCompare(b)), metadata]) : null
  const total = renders ? Object.values(renders).filter(path => typeof path === 'string' && path).length : 0
  const key = JSON.stringify([sessionId, toolCallId, path, label, signature])
  useEffect(() => {
    if (file?.kind !== 'image' || typeof file.resolveUrl !== 'function' || !path) return undefined
    let live = true
    const attributable = sessionId && toolCallId && signature && renders[label] === path
    if (attributable) recordView(sessionId, toolCallId, signature, label, null, metadata, total)
    Promise.resolve().then(() => file.resolveUrl()).then(url => {
      if (!live) return
      if (typeof url !== 'string' || !url) throw new Error('No URL')
      setLoaded({ key, url })
      if (attributable) recordView(sessionId, toolCallId, signature, label, url, metadata, total)
    }).catch(() => {
      if (live && attributable) recordView(sessionId, toolCallId, signature, label, null, metadata, total, 'error')
    })
    return () => {
      live = false
      if (attributable) recordView(sessionId, toolCallId, signature, label, null, metadata, total, 'error')
    }
  }, [path, key, file?.kind])
  if (!file || file.kind !== 'image' || loaded?.key !== key || !loaded.url) return fallback
  return jsxs('figure', {
    style: { margin: 0, maxWidth: 420, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 8, overflow: 'hidden' },
    children: [
      jsx('img', { alt: `${displayName(label).replace(' · ', ' ')} drawing`, src: loaded.url, onError: () => { removeView(sessionId, toolCallId, label, loaded.url); setLoaded(null) }, style: { display: 'block', width: '100%', height: 'auto' } }),
      jsx('figcaption', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.06em', padding: '6px 8px' }, children: displayName(label).toUpperCase() }),
    ],
  })
}

function DrawingPane() {
  // Renderer sessionId is stored id when available, otherwise runtime id.
  const stored = sdk.useValue(sdk.host.state.focusedStoredSessionId)
  const runtime = sdk.useValue(sdk.host.state.focusedSessionId)
  const all = sdk.useValue(sheets)
  const [selection, setSelection] = useState(null)
  const [zoom, setZoom] = useState(null)
  const id = stored || runtime
  useEffect(() => {
    if (id) rankSheets(id, runtime)
  }, [id, runtime])
  const session = id && Object.hasOwn(all, id) ? all[id] : null
  const candidate = session?.selected && Object.hasOwn(session.candidates, session.selected) ? session.candidates[session.selected] : null
  const views = candidate && !candidate.ambiguous ? candidate.views : {}
  const names = orderedNames(Object.fromEntries(Object.entries(views || {}).filter(([, view]) => view.url)))
  const identity = JSON.stringify([id, session?.selected, candidate?.signature])
  const selected = selection?.identity === identity && names.includes(selection.name) ? selection.name : names[0]
  const zoomed = zoom?.identity === identity && zoom?.value === 2
  if (!names.length) {
    const loading = Object.values(views || {}).some(view => view.status === 'loading')
    const error = session?.historyError || Object.values(views || {}).some(view => view.status === 'error')
    return jsx(sdk.EmptyState, {
      title: loading ? 'Loading drawing' : error ? 'Drawing unavailable' : 'No drawing available',
      description: loading ? 'Resolving the latest observed drawing in this chat.' : error ? 'The drawing or its transcript order could not be verified. Open the transcript and try again.' : 'Emit preview MEDIA: lines in this chat and open its transcript. The pane shows the latest observed sheet when its order can be verified.',
    })
  }
  const model = candidate.metadata
  const detail = asObject(model.metadata[selected]) || {}
  const region = asObject(detail.region)
  const coords = region && ['x_min', 'y_min', 'x_max', 'y_max'].every(key => typeof region[key] === 'number' && Number.isFinite(region[key]))
    ? ` (${region.x_min}, ${region.y_min})–(${region.x_max}, ${region.y_max})` : ''
  const regionLabel = typeof region?.label === 'string' ? region.label : null
  const actualView = typeof detail.view === 'string' ? detail.view : null
  const resolution = typeof detail.resolution === 'number' && Number.isFinite(detail.resolution) ? detail.resolution : null
  const sourceName = model.path?.split(/[\\/\\\\]/).pop()
  const Button = sdk.Button || 'button'
  const buttonVariant = sdk.Button ? { variant: 'outline', size: 'sm' } : {}
  const buttonStyle = { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6, padding: 6, color: 'var(--ui-text-secondary)', background: 'transparent', cursor: 'pointer' }
  return jsxs('section', {
    'aria-label': 'Drawing sheet',
    style: { display: 'flex', flexDirection: 'column', gap: 10, padding: 12, minWidth: 0, overflow: 'auto' },
    children: [
      jsxs('div', { style: { minWidth: 0, overflowWrap: 'anywhere' }, children: [
        jsx('strong', { children: sourceName || 'Source model unavailable' }),
        model.type && jsx('span', { style: { color: 'var(--ui-text-secondary)', marginLeft: 8 }, children: model.type }),
        model.path && jsx('div', { style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: model.path }),
        model.hash && jsx('div', { title: model.hash, style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: `Source SHA-256: ${model.hash.slice(0, 12)}…` }),
      ] }),
      jsxs('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }, children: [
        jsx('strong', { children: displayName(selected) }),
        jsx(Button, { ...buttonVariant, type: 'button', style: buttonStyle, 'aria-pressed': zoomed, onClick: () => setZoom({ identity, value: zoomed ? 1 : 2 }), children: zoomed ? 'Fit' : 'Zoom 2×' }),
      ] }),
      jsxs('figure', { style: { margin: 0, minWidth: 0 }, children: [
        jsx('div', { style: { overflow: 'auto', maxWidth: '100%', maxHeight: '65vh', border: '1px solid var(--ui-stroke-secondary)' }, children: jsx('img', { 'data-preview': true, alt: `${displayName(selected).replace(' · ', ' ')} drawing`, src: views[selected].url, onError: () => removeView(id, session.selected, selected, views[selected].url), style: { display: 'block', width: zoomed ? '200%' : '100%', maxWidth: 'none', height: 'auto' } }) }),
        jsxs('figcaption', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, overflowWrap: 'anywhere', marginTop: 6 }, children: [
          actualView && `View: ${displayName(actualView)}. `,
          resolution && `Resolution: ${resolution} × ${resolution} px. `,
          regionLabel && `Region: ${regionLabel}${coords} (normalized).`,
        ] }),
      ] }),
      jsxs('div', { children: [
        jsx('div', { style: { fontSize: 12, color: 'var(--ui-text-secondary)', marginBottom: 6 }, children: `Available views: ${names.length} of ${candidate.total} returned` }),
        jsx('div', { role: 'group', 'aria-label': 'Drawing views', style: { display: 'flex', gap: 6, overflowX: 'auto', maxWidth: '100%' }, children: names.map(name => jsxs(Button, {
          ...buttonVariant, key: name, type: 'button', 'data-view': name, 'aria-pressed': name === selected, 'aria-label': `${displayName(name)} drawing`, onClick: () => setSelection({ identity, name }),
          style: { ...buttonStyle, display: 'flex', flexDirection: 'column', whiteSpace: 'normal', flex: '0 0 76px', borderColor: name === selected ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)' },
          children: [jsx('img', { alt: '', src: views[name].url, onError: () => removeView(id, session.selected, name, views[name].url), style: { display: 'block', width: '100%', height: 48, objectFit: 'contain' } }), jsx('span', { style: { display: 'block', fontSize: 11, overflowWrap: 'anywhere' }, children: displayName(name) })],
        })) }),
        names.length < candidate.total && jsx('p', { style: { fontSize: 12, color: 'var(--ui-text-secondary)' }, children: 'Ask the assistant to show the remaining views in this chat. If a view failed to load, reopen its attachment.' }),
      ] }),
    ],
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
