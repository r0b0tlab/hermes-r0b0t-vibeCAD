import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// The media slot has no transcript position. Do not infer it from mount or URL
// completion order: virtualized history can remount older cards at any time.
const sheets = sdk.atom({})
const pending = new Map()
const TOOL = 'vibecad_generate_preview_renders'
const BRIDGE = 'tool_call'
const VIEW_ORDER = ['iso', 'top', 'front', 'back', 'left', 'right', 'bottom']
const MAX_SESSIONS = 12
const MAX_CANDIDATES_PER_SESSION = 24

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

function pruneCandidates(candidates, orderedIds) {
  const keys = Object.keys(candidates)
  if (keys.length <= MAX_CANDIDATES_PER_SESSION) return candidates
  const keep = new Set((orderedIds || []).slice(-MAX_CANDIDATES_PER_SESSION))
  for (const key of keys.slice(-MAX_CANDIDATES_PER_SESSION)) {
    if (keep.size >= MAX_CANDIDATES_PER_SESSION) break
    keep.add(key)
  }
  const next = {}
  for (const key of keys) if (keep.has(key)) next[key] = candidates[key]
  return next
}

function setSession(sessionId, change) {
  const all = sheets.get()
  const previous = Object.hasOwn(all, sessionId) ? all[sessionId] : { candidates: {}, orderedIds: [], historyError: false }
  const updated = change(previous)
  const boundedSession = { ...updated, candidates: pruneCandidates(updated.candidates || {}, updated.orderedIds) }
  // Re-insert sessionId last so Map/Object key order acts as an access-touched LRU.
  const nextAll = {}
  for (const key of Object.keys(all)) {
    if (key !== sessionId) nextAll[key] = all[key]
  }
  nextAll[sessionId] = boundedSession
  const focusedStored = sdk.host?.state?.focusedStoredSessionId?.get?.()
  const focusedRuntime = sdk.host?.state?.focusedSessionId?.get?.()
  for (const key of Object.keys(nextAll)) {
    if (Object.keys(nextAll).length <= MAX_SESSIONS) break
    if (key === sessionId || key === focusedStored || key === focusedRuntime) continue
    delete nextAll[key]
    pending.delete(key)
  }
  sheets.set(nextAll)
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
      const orderedIds = []
      let ambiguousTail = false
      for (const row of rows) {
        if (!Object.hasOwn(state.candidates, row.tool_call_id)) continue
        if (counts.get(row.tool_call_id) === 1 && !state.candidates[row.tool_call_id]?.ambiguous) {
          orderedIds.push(row.tool_call_id)
          ambiguousTail = false
        } else {
          ambiguousTail = true
        }
      }
      // If the latest observed call in transcript order is ambiguous, never fall back to an older call.
      return { ...state, orderedIds: ambiguousTail ? [] : orderedIds, historyError: false }
    })
  } catch {
    // No chronology means no truthful latest sheet; the inline card still works.
    if (pending.get(sessionId) === ticket) setSession(sessionId, state => ({ ...state, orderedIds: [], historyError: true }))
  }
}

function parseGeometry(raw) {
  const geo = asObject(raw)
  const size = asObject(geo?.bbox_size_mm)
  if (!geo || !size) return null
  const x = Number(size.x), y = Number(size.y), z = Number(size.z), zMin = Number(geo.z_min_mm)
  if (![x, y, z, zMin].every(Number.isFinite)) return null
  const parts = Number.isInteger(geo.part_count) && geo.part_count > 0 ? geo.part_count : null
  const triangles = Number.isInteger(geo.triangle_count) && geo.triangle_count > 0 ? geo.triangle_count : null
  return { x, y, z, zMin, parts, triangles }
}

// Only data returned by the tool is presented as model provenance.
function sheetMetadata(result) {
  const data = asObject(result) || {}
  const path = typeof data.step_file === 'string' ? data.step_file : typeof data.mesh_file === 'string' ? data.mesh_file : null
  const sourceHash = data.source_sha256 ?? data.source_step_sha256
  const hash = typeof sourceHash === 'string' && /^[a-f0-9]{64}$/i.test(sourceHash) ? sourceHash : null
  const metadata = asObject(data.render_metadata) || {}
  const geometry = parseGeometry(data.geometry_summary)
  return { path, type: path ? (data.step_file === path ? 'STEP' : 'STL') : null, hash, metadata, geometry }
}

// Group chronologically verified calls into revision sheets. Calls sharing the
// exact same 64-hex source_sha256 and model path (e.g. full-frame views +
// targeted detail region calls on the same STEP/STL) fuse into one sheet; calls
// without a 64-hex hash remain strictly isolated per tool_call_id.
function buildRevisions(orderedIds, candidates) {
  const revisions = []
  for (const callId of orderedIds || []) {
    const candidate = Object.hasOwn(candidates, callId) ? candidates[callId] : null
    if (!candidate || candidate.ambiguous) continue
    const meta = candidate.metadata || {}
    const canFuse = Boolean(meta.hash && meta.path)
    const key = canFuse ? `hash:${meta.type || ''}:${meta.path}:${meta.hash}` : `call:${callId}`
    const taggedViews = {}
    for (const [label, entry] of Object.entries(candidate.views || {})) {
      taggedViews[label] = { ...entry, callId }
    }
    const existingIndex = canFuse ? revisions.findIndex(item => item.key === key) : -1
    if (existingIndex >= 0) {
      const prior = revisions.splice(existingIndex, 1)[0]
      const expectedSet = new Set(prior.expectedSet)
      for (const name of candidate.expectedKeys || []) expectedSet.add(name)
      const mergedMeta = {
        ...prior.metadata,
        ...meta,
        metadata: { ...prior.metadata.metadata, ...meta.metadata },
        geometry: meta.geometry || prior.metadata.geometry || null,
      }
      revisions.push({
        key,
        signature: `${prior.signature}|${candidate.signature}`,
        views: { ...prior.views, ...taggedViews },
        metadata: mergedMeta,
        expectedSet,
        total: expectedSet.size,
      })
    } else {
      const expectedSet = new Set(candidate.expectedKeys || [])
      revisions.push({
        key,
        signature: candidate.signature,
        views: taggedViews,
        metadata: { ...meta, metadata: { ...meta.metadata } },
        expectedSet,
        total: expectedSet.size,
      })
    }
  }
  return revisions
}

function recordView(sessionId, callId, signature, label, url, filePath, metadata, expectedKeys, status = 'loading') {
  setSession(sessionId, state => {
    const candidate = Object.hasOwn(state.candidates, callId) ? state.candidates[callId] : null
    // Same call ID with different results is ambiguous, never merge them.
    if (candidate && candidate.signature !== signature) {
      return {
        ...state,
        candidates: { ...state.candidates, [callId]: { ambiguous: true } },
        orderedIds: (state.orderedIds || []).filter(item => item !== callId),
      }
    }
    if (candidate?.ambiguous) return state
    const views = { ...candidate?.views }
    if (url) views[label] = { url, filePath, status: 'ready' }
    else if (!views[label]?.url) views[label] = { filePath, status }
    return {
      ...state,
      candidates: { ...state.candidates, [callId]: { signature, views, metadata, expectedKeys } },
    }
  })
  const focusedStored = sdk.host.state.focusedStoredSessionId.get()
  const focusedRuntime = sdk.host.state.focusedSessionId.get()
  rankSheets(sessionId, sessionId === (focusedStored || focusedRuntime) ? focusedRuntime : null)
}

// Virtualized transcript unmounts must not destroy already-resolved views or
// trigger session.history storms; only drop an unfinished loading placeholder.
function cancelLoadingView(sessionId, callId, label) {
  if (!sessionId || !callId) return
  const all = sheets.get()
  const session = Object.hasOwn(all, sessionId) ? all[sessionId] : null
  const candidate = session?.candidates && Object.hasOwn(session.candidates, callId) ? session.candidates[callId] : null
  if (!candidate?.views || candidate.views[label]?.url || candidate.views[label]?.status !== 'loading') return
  setSession(sessionId, state => {
    const current = Object.hasOwn(state.candidates, callId) ? state.candidates[callId] : null
    if (!current?.views || current.views[label]?.url || current.views[label]?.status !== 'loading') return state
    const views = { ...current.views }
    delete views[label]
    return { ...state, candidates: { ...state.candidates, [callId]: { ...current, views } } }
  })
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

async function copyText(pluginCtx, text, message) {
  if (!text) return false
  let ok = false
  if (typeof sdk.writeClipboardText === 'function') {
    try { ok = Boolean(await sdk.writeClipboardText(text)) } catch { ok = false }
  }
  if (!ok && typeof pluginCtx?.os?.writeClipboard === 'function') {
    try { ok = Boolean(await pluginCtx.os.writeClipboard(text)) } catch { ok = false }
  }
  if (ok && message) sdk.host?.notify?.({ kind: 'info', message })
  return ok
}

async function revealOrCopyPath(pluginCtx, targetPath) {
  if (!targetPath) return false
  if (typeof pluginCtx?.os?.revealPath === 'function') {
    try {
      if (await pluginCtx.os.revealPath(targetPath)) return true
    } catch {
      // Fall through to clipboard copy on remote or unsupported hosts.
    }
  }
  return copyText(pluginCtx, targetPath, 'Copied path to clipboard')
}

function roundCoord(value) {
  return Math.round(Math.max(0, Math.min(1, value)) * 1000) / 1000
}

function formatNum(value) {
  return Number(value.toFixed(3)).toString()
}

function DrawingCard({ file, result, fallback, sessionId, toolCallId }) {
  const [loaded, setLoaded] = useState(null)
  const path = file?.path
  const label = file ? viewName(file, result) : 'drawing'
  const renders = asObject(asObject(result)?.renders)
  const metadata = sheetMetadata(result)
  // Bind context to this revision as well as its image paths.
  const signature = renders ? JSON.stringify([Object.entries(renders).sort(([a], [b]) => a.localeCompare(b)), metadata]) : null
  const expectedKeys = renders ? Object.entries(renders).filter(([, p]) => typeof p === 'string' && p).map(([k]) => k) : []
  const key = JSON.stringify([sessionId, toolCallId, path, label, signature])
  useEffect(() => {
    if (file?.kind !== 'image' || typeof file.resolveUrl !== 'function' || !path) return undefined
    let live = true
    const attributable = sessionId && toolCallId && signature && renders[label] === path
    if (attributable) recordView(sessionId, toolCallId, signature, label, null, path, metadata, expectedKeys)
    Promise.resolve().then(() => file.resolveUrl()).then(url => {
      if (!live) return
      if (typeof url !== 'string' || !url) throw new Error('No URL')
      setLoaded({ key, url })
      if (attributable) recordView(sessionId, toolCallId, signature, label, url, path, metadata, expectedKeys)
    }).catch(() => {
      if (live && attributable) recordView(sessionId, toolCallId, signature, label, null, path, metadata, expectedKeys, 'error')
    })
    return () => {
      live = false
      if (attributable) cancelLoadingView(sessionId, toolCallId, label)
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

function DrawingPane({ pluginCtx }) {
  // Renderer sessionId is stored id when available, otherwise runtime id.
  const stored = sdk.useValue(sdk.host.state.focusedStoredSessionId)
  const runtime = sdk.useValue(sdk.host.state.focusedSessionId)
  const all = sdk.useValue(sheets)
  const [selection, setSelection] = useState(null)
  const [zoom, setZoom] = useState(null)
  const [compareState, setCompareState] = useState(null)
  const [cropState, setCropState] = useState(null)
  const pan = useRef(null)
  const cropDrag = useRef(null)
  const viewport = useRef(null)
  const id = stored || runtime
  useEffect(() => {
    if (id) rankSheets(id, runtime)
  }, [id, runtime])

  const session = id && Object.hasOwn(all, id) ? all[id] : null
  const revisions = session ? buildRevisions(session.orderedIds, session.candidates) : []
  const latest = revisions.length ? revisions[revisions.length - 1] : null
  const latestReadyNames = latest ? orderedNames(Object.fromEntries(Object.entries(latest.views || {}).filter(([, view]) => view.url))) : []

  const readyRevisions = revisions.filter(rev => Object.values(rev.views || {}).some(view => view.url))
  const latestEpoch = latest ? JSON.stringify([id, latest.key]) : ''
  const comparing = Boolean(compareState?.epoch === latestEpoch && compareState.active && readyRevisions.length >= 2)
  const activeRevIndex = comparing ? readyRevisions.length - 2 : readyRevisions.length - 1
  const activeRevision = latestReadyNames.length && activeRevIndex >= 0 ? readyRevisions[activeRevIndex] : null

  const views = activeRevision ? activeRevision.views : latest?.views || {}
  const names = activeRevision ? orderedNames(Object.fromEntries(Object.entries(views).filter(([, view]) => view.url))) : []
  const selectionIdentity = JSON.stringify([id, latest?.key])
  const selected = selection?.identity === selectionIdentity && names.includes(selection.name) ? selection.name : names[0]
  const identity = JSON.stringify([id, activeRevision?.key, activeRevision?.signature])
  const zoomFactor = zoom?.identity === identity && (zoom.value === 2 || zoom.value === 4) ? zoom.value : 1
  const zoomed = zoomFactor > 1

  useEffect(() => {
    pan.current = null
    cropDrag.current = null
    if (viewport.current) {
      viewport.current.scrollLeft = 0
      viewport.current.scrollTop = 0
    }
  }, [identity, selected, zoomFactor])

  if (!names.length) {
    const loading = Object.values(views || {}).some(view => view.status === 'loading')
    const error = session?.historyError || Object.values(views || {}).some(view => view.status === 'error')
    return jsx(sdk.EmptyState, {
      title: loading ? 'Loading drawing' : error ? 'Drawing unavailable' : 'No drawing available',
      description: loading ? 'Resolving the latest observed drawing in this chat.' : error ? 'The drawing or its transcript order could not be verified. Open the transcript and try again.' : 'Emit preview MEDIA: lines in this chat and open its transcript. The pane shows the latest observed sheet when its order can be verified.',
    })
  }

  const model = activeRevision.metadata
  const detail = asObject(model.metadata[selected]) || {}
  const region = asObject(detail.region)
  const coords = region && ['x_min', 'y_min', 'x_max', 'y_max'].every(key => typeof region[key] === 'number' && Number.isFinite(region[key]))
    ? ` (${region.x_min}, ${region.y_min})–(${region.x_max}, ${region.y_max})` : ''
  const regionLabel = typeof region?.label === 'string' ? region.label : null
  const actualView = typeof detail.view === 'string' ? detail.view : null
  const resolution = typeof detail.resolution === 'number' && Number.isFinite(detail.resolution) ? detail.resolution : null
  const sourceName = model.path?.split(/[\\/\\\\]/).pop()
  const geometry = model.geometry
  const datumOff = Boolean(geometry && Math.abs(geometry.zMin) > 0.01)

  const cropIdentity = JSON.stringify([identity, selected])
  const cropEnabled = Boolean(!region && !zoomed && cropState?.identity === cropIdentity && cropState.enabled)
  const cropBox = cropEnabled ? cropState.box : null

  const previousRevision = readyRevisions.length >= 2 ? readyRevisions[readyRevisions.length - 2] : null
  const canComparePrev = Boolean(previousRevision && (comparing || previousRevision.views?.[selected]?.url))

  const Button = sdk.Button || 'button'
  const buttonVariant = sdk.Button ? { variant: 'outline', size: 'sm' } : {}
  const buttonStyle = { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6, padding: '4px 8px', fontSize: 12, color: 'var(--ui-text-secondary)', background: 'transparent', cursor: 'pointer' }

  const relativePoint = (node, event) => {
    const rect = node.getBoundingClientRect?.()
    if (!rect || rect.width <= 0 || rect.height <= 0) return null
    return { x: roundCoord((event.clientX - rect.left) / rect.width), y: roundCoord((event.clientY - rect.top) / rect.height) }
  }

  const startPointer = event => {
    if (event.button !== 0) return
    const node = event.currentTarget
    if (cropEnabled) {
      const pt = relativePoint(node, event)
      if (!pt) return
      cropDrag.current = { id: event.pointerId, x0: pt.x, y0: pt.y }
      node.setPointerCapture?.(event.pointerId)
      event.preventDefault()
      return
    }
    if (!zoomed || pan.current) return
    pan.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: node.scrollLeft, top: node.scrollTop }
    node.setPointerCapture?.(event.pointerId)
    event.preventDefault()
  }

  const movePointer = event => {
    if (cropEnabled && cropDrag.current?.id === event.pointerId) {
      const pt = relativePoint(event.currentTarget, event)
      if (!pt) return
      const x_min = roundCoord(Math.min(cropDrag.current.x0, pt.x))
      const y_min = roundCoord(Math.min(cropDrag.current.y0, pt.y))
      const x_max = roundCoord(Math.max(cropDrag.current.x0, pt.x))
      const y_max = roundCoord(Math.max(cropDrag.current.y0, pt.y))
      if (x_max - x_min >= 0.005 && y_max - y_min >= 0.005) {
        setCropState({ identity: cropIdentity, enabled: true, box: { x_min, y_min, x_max, y_max } })
      }
      return
    }
    const origin = pan.current
    if (!zoomed || !origin || origin.id !== event.pointerId) return
    event.currentTarget.scrollLeft = origin.left - (event.clientX - origin.x)
    event.currentTarget.scrollTop = origin.top - (event.clientY - origin.y)
  }

  const stopPointer = event => {
    if (cropDrag.current?.id === event.pointerId) {
      cropDrag.current = null
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
      return
    }
    if (pan.current?.id !== event.pointerId) return
    pan.current = null
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  const keyPan = event => {
    if (!zoomed) return
    const movement = { ArrowLeft: [-50, 0], ArrowRight: [50, 0], ArrowUp: [0, -50], ArrowDown: [0, 50] }[event.key]
    if (!movement) return
    event.currentTarget.scrollLeft += movement[0]
    event.currentTarget.scrollTop += movement[1]
    event.preventDefault()
  }

  const sectionKeyDown = event => {
    if (event.altKey || event.ctrlKey || event.metaKey) return
    if (event.key === '[' || event.key === ']') {
      if (names.length < 2) return
      const idx = names.indexOf(selected)
      const next = names[(idx + (event.key === ']' ? 1 : names.length - 1)) % names.length]
      setSelection({ identity: selectionIdentity, name: next })
      event.preventDefault?.()
    } else if ((event.key === 'c' || event.key === 'C') && canComparePrev) {
      setCompareState({ epoch: latestEpoch, active: !comparing })
      event.preventDefault?.()
    }
  }

  const insertCropPrompt = async () => {
    if (!cropBox) return
    const payload = JSON.stringify({ label: 'detail', x_min: cropBox.x_min, y_min: cropBox.y_min, x_max: cropBox.x_max, y_max: cropBox.y_max })
    const baseView = actualView || selected
    const target = model.path || 'the current model'
    const prompt = `Use vibecad_generate_preview_renders on ${target} with views ["${baseView}"] and region ${payload} at resolution 1600, then inspect the pixels.`
    let inserted = false
    if (typeof sdk.host?.composer?.insertText === 'function') {
      try { inserted = Boolean(await sdk.host.composer.insertText(id || null, prompt)) } catch { inserted = false }
    }
    if (!inserted) await copyText(pluginCtx, prompt, 'Copied detail region prompt to clipboard')
  }

  const activeEntry = views[selected]

  return jsxs('section', {
    'aria-label': 'Drawing sheet',
    onKeyDown: sectionKeyDown,
    style: { display: 'flex', flexDirection: 'column', gap: 10, padding: 12, minWidth: 0, overflow: 'auto' },
    children: [
      jsxs('div', { style: { minWidth: 0, overflowWrap: 'anywhere' }, children: [
        jsx('strong', { children: sourceName || 'Source model unavailable' }),
        model.type && jsx('span', { style: { color: 'var(--ui-text-secondary)', marginLeft: 8 }, children: model.type }),
        model.path && jsx('div', { style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: model.path }),
        model.hash && jsx('div', { title: model.hash, style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: `Source SHA-256: ${model.hash.slice(0, 12)}…` }),
        geometry && jsx('div', {
          style: { color: 'var(--ui-text-secondary)', fontSize: 12, marginTop: 2 },
          children: `${formatNum(geometry.x)} × ${formatNum(geometry.y)} × ${formatNum(geometry.z)} mm · Zmin ${formatNum(geometry.zMin)} mm${geometry.parts ? ` · ${geometry.parts} ${geometry.parts === 1 ? 'part' : 'parts'}` : ''}`,
        }),
        datumOff && jsx('div', {
          style: { color: 'var(--ui-accent)', fontSize: 12, marginTop: 2 },
          children: 'Bed datum off Z=0 — verify bottom placement before slicing.',
        }),
        (model.path || model.hash || activeEntry?.filePath) && jsxs('div', {
          style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 },
          children: [
            model.path && jsx(Button, { ...buttonVariant, type: 'button', 'data-action': 'reveal-model', style: buttonStyle, onClick: () => revealOrCopyPath(pluginCtx, model.path), children: 'Reveal file' }),
            activeEntry?.filePath && model.path && jsx(Button, { ...buttonVariant, type: 'button', 'data-action': 'reveal-png', style: buttonStyle, onClick: () => revealOrCopyPath(pluginCtx, activeEntry.filePath), children: 'Reveal PNG' }),
            model.hash && jsx(Button, { ...buttonVariant, type: 'button', 'data-action': 'copy-hash', style: buttonStyle, onClick: () => copyText(pluginCtx, model.hash, 'Copied source SHA-256'), children: 'Copy SHA-256' }),
          ],
        }),
      ] }),
      readyRevisions.length > 1 && jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid var(--ui-stroke-secondary)', paddingTop: 8 },
        children: [
          jsxs('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, flexWrap: 'wrap' }, children: [
            jsx('span', { style: { fontSize: 12, color: 'var(--ui-text-secondary)' }, children: `Sheet ${activeRevIndex + 1} of ${readyRevisions.length}` }),
            jsxs('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' }, children: [
              canComparePrev && jsx(Button, {
                ...buttonVariant, type: 'button', 'data-compare': true, 'aria-pressed': comparing,
                style: { ...buttonStyle, borderColor: comparing ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)' },
                onClick: () => setCompareState({ epoch: latestEpoch, active: !comparing }),
                children: comparing ? 'Latest' : 'Compare prev',
              }),
            ] }),
          ] }),
          comparing && jsx('div', {
            style: { fontSize: 12, color: 'var(--ui-accent)' },
            children: 'Older revision shown for comparison — click Latest to return.',
          }),
        ],
      }),
      jsxs('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }, children: [
        jsx('strong', { children: displayName(selected) }),
        jsxs('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' }, children: [
          !region && !zoomed && jsx(Button, {
            ...buttonVariant, type: 'button', 'data-action': 'toggle-crop', 'aria-pressed': cropEnabled,
            style: { ...buttonStyle, borderColor: cropEnabled ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)' },
            onClick: () => setCropState({ identity: cropIdentity, enabled: !cropEnabled, box: null }),
            children: cropEnabled ? 'Cancel crop' : 'Select region',
          }),
          jsx(Button, { ...buttonVariant, type: 'button', style: buttonStyle, 'aria-pressed': zoomed, onClick: () => setZoom({ identity, value: zoomed ? 1 : 2 }), children: zoomed ? 'Fit' : 'Zoom 2×' }),
          jsx(Button, { ...buttonVariant, type: 'button', style: { ...buttonStyle, borderColor: zoomFactor === 4 ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)' }, 'aria-pressed': zoomFactor === 4, onClick: () => setZoom({ identity, value: zoomFactor === 4 ? 1 : 4 }), children: 'Zoom 4×' }),
        ] }),
      ] }),
      jsxs('figure', { style: { margin: 0, minWidth: 0 }, children: [
        jsxs('div', {
          ref: viewport, 'data-pan-viewport': true, tabIndex: 0, role: 'region',
          'aria-label': zoomed ? 'Zoomed drawing: drag or use arrow keys to pan' : cropEnabled ? 'Drag on drawing to select a normalized detail region' : 'Drawing preview',
          onPointerDown: startPointer, onPointerMove: movePointer, onPointerUp: stopPointer,
          onPointerCancel: stopPointer, onLostPointerCapture: stopPointer, onKeyDown: keyPan,
          style: { position: 'relative', overflow: 'auto', maxWidth: '100%', maxHeight: '65vh', border: '1px solid var(--ui-stroke-secondary)', cursor: cropEnabled ? 'crosshair' : zoomed ? 'grab' : 'default', touchAction: zoomed || cropEnabled ? 'none' : 'auto' },
          children: [
            jsx('img', { 'data-preview': true, draggable: false, alt: `${displayName(selected).replace(' · ', ' ')} drawing`, src: activeEntry.url, onError: () => removeView(id, activeEntry.callId, selected, activeEntry.url), style: { display: 'block', width: zoomed ? `${zoomFactor * 100}%` : '100%', maxWidth: 'none', height: 'auto', userSelect: 'none' } }),
            cropBox && jsx('div', {
              'data-region-box': true,
              style: {
                position: 'absolute',
                left: `${cropBox.x_min * 100}%`,
                top: `${cropBox.y_min * 100}%`,
                width: `${(cropBox.x_max - cropBox.x_min) * 100}%`,
                height: `${(cropBox.y_max - cropBox.y_min) * 100}%`,
                border: '2px solid var(--ui-accent)',
                pointerEvents: 'none',
                boxSizing: 'border-box',
              },
            }),
          ],
        }),
        zoomed && jsx('div', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, marginTop: 6 }, children: 'Drag the drawing or use arrow keys to pan.' }),
        cropEnabled && !cropBox && jsx('div', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, marginTop: 6 }, children: 'Drag across the preview to frame a 1600 px detail region.' }),
        cropBox && jsxs('div', {
          style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 6 },
          children: [
            jsx('span', { style: { fontSize: 12, color: 'var(--ui-text-secondary)' }, children: `Selected: (${cropBox.x_min}, ${cropBox.y_min})–(${cropBox.x_max}, ${cropBox.y_max})` }),
            jsx(Button, { ...buttonVariant, type: 'button', 'data-action': 'insert-crop-prompt', style: { ...buttonStyle, borderColor: 'var(--ui-accent)' }, onClick: insertCropPrompt, children: 'Ask Hermes to inspect region' }),
          ],
        }),
        jsxs('figcaption', { style: { color: 'var(--ui-text-secondary)', fontSize: 12, overflowWrap: 'anywhere', marginTop: 6 }, children: [
          actualView && `View: ${displayName(actualView)}. `,
          resolution && `Resolution: ${resolution} × ${resolution} px. `,
          regionLabel && `Region: ${regionLabel}${coords} (normalized).`,
        ] }),
      ] }),
      jsxs('div', { children: [
        jsx('div', { style: { fontSize: 12, color: 'var(--ui-text-secondary)', marginBottom: 6 }, children: `Available views: ${names.length} of ${activeRevision.total} returned` }),
        jsx('div', { role: 'group', 'aria-label': 'Drawing views', style: { display: 'flex', gap: 6, overflowX: 'auto', maxWidth: '100%' }, children: names.map(name => jsxs(Button, {
          ...buttonVariant, key: name, type: 'button', 'data-view': name, 'aria-pressed': name === selected, 'aria-label': `${displayName(name)} drawing`, onClick: () => setSelection({ identity: selectionIdentity, name }),
          style: { ...buttonStyle, padding: 6, display: 'flex', flexDirection: 'column', whiteSpace: 'normal', flex: '0 0 76px', borderColor: name === selected ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)' },
          children: [jsx('img', { alt: '', src: views[name].url, onError: () => removeView(id, views[name].callId, name, views[name].url), style: { display: 'block', width: '100%', height: 48, objectFit: 'contain' } }), jsx('span', { style: { display: 'block', fontSize: 11, overflowWrap: 'anywhere' }, children: displayName(name) })],
        })) }),
        names.length < activeRevision.total && jsx('p', { style: { fontSize: 12, color: 'var(--ui-text-secondary)' }, children: 'Ask the assistant to show the remaining views in this chat. If a view failed to load, reopen its attachment.' }),
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
    ctx.register({ id: 'drawing-pane', area: 'panes', title: 'vibeCAD', data: { placement: 'right', width: '300px' }, render: () => jsx(DrawingPane, { pluginCtx: ctx }) })
  },
}
