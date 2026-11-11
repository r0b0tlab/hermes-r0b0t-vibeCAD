// Run: node --experimental-vm-modules --test tests/desktop.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const tick = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)) }
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

async function setup({ media = true, nativeButtons = false, os = null, composer = null } = {}) {
  const atom = value => ({ get: () => value, set: next => { value = next } })
  const focusedStoredSessionId = atom(null), focusedSessionId = atom(null)
  const history = new Map(), requests = [], clipboard = [], notifications = []
  let request = async (_method, { session_id }) => ({ messages: history.get(session_id) || [] })
  const sdk = {
    atom, useValue: atom => atom.get(), EmptyState: 'EmptyState',
    writeClipboardText: async value => { clipboard.push(value); return true },
    host: {
      state: { focusedStoredSessionId, focusedSessionId },
      request: (...args) => { requests.push(args); return request(...args) },
      notify: note => notifications.push(note),
      ...(composer ? { composer } : {}),
    },
    ...(media ? { TOOL_MEDIA_RENDERER_AREA: 'transcript.toolMedia' } : {}),
    ...(nativeButtons ? { Button: 'button' } : {}),
  }
  let active
  const react = {
    useState(initial) { const state = active, i = state.index++; if (!(i in state.hooks)) state.hooks[i] = initial; return [state.hooks[i], value => { state.hooks[i] = typeof value === 'function' ? value(state.hooks[i]) : value }] },
    useRef(initial) { const state = active, i = state.index++; if (!(i in state.hooks)) state.hooks[i] = { current: initial }; return state.hooks[i] },
    useEffect(fn, deps) { const state = active, i = state.index++; const old = state.effects[i]; if (!old || deps.some((value, j) => !Object.is(value, old.deps[j]))) state.scheduled.push(() => { old?.cleanup?.(); state.effects[i] = { deps, cleanup: fn() } }) },
  }
  const jsx = (type, props) => ({ type, props: props || {} })
  const modules = { '@hermes/plugin-sdk': sdk, react, 'react/jsx-runtime': { jsx, jsxs: jsx } }
  const context = vm.createContext({ console })
  const module = new vm.SourceTextModule(source, { context })
  await module.link(specifier => new vm.SyntheticModule(Object.keys(modules[specifier]), function () { for (const [key, value] of Object.entries(modules[specifier])) this.setExport(key, value) }, { context }))
  await module.evaluate()
  const registrations = []
  module.namespace.default.register({ register: entry => registrations.push(entry), ...(os ? { os } : {}) })
  const mediaContribution = registrations.find(c => c.area === 'transcript.toolMedia')
  const paneContribution = registrations.find(c => c.area === 'panes')
  const mount = element => {
    const state = { hooks: [], effects: [], scheduled: [], index: 0, element }
    return {
      render(props = state.element.props) {
        state.element = { ...state.element, props }; state.index = 0; state.scheduled = []; active = state
        const output = state.element.type(props); active = null
        for (const effect of state.scheduled) effect()
        return output
      },
      unmount() { for (const effect of state.effects) effect?.cleanup?.() },
    }
  }
  const pane = mount(paneContribution.render())
  return { sdk, pane, mount, registrations, mediaContribution, history, requests, clipboard, notifications, setRequest: fn => { request = fn }, stored: focusedStoredSessionId, runtime: focusedSessionId }
}
const rows = (...ids) => ids.map(tool_call_id => ({ role: 'tool', name: 'vibecad_generate_preview_renders', tool_call_id }))
// A deferred tool call is stored as the bridge: the row's own name is
// "tool_call" and the real tool name sits in args.calls[0].name. This is the
// shape upstream's session.history projection actually produces.
const bridged = (...ids) => ids.map(tool_call_id => ({
  role: 'tool',
  name: 'tool_call',
  tool_call_id,
  args: { calls: [{ name: 'vibecad_generate_preview_renders', arguments: { resolution: '800' } }] },
}))
const card = (env, { session = 'a', id = 'one', view = 'iso', renders, resolver, fallback = 'BUILTIN', result = {} } = {}) => {
  const path = renders?.[view] || `/${id}/${view}.png`
  const file = { path, name: `preview_${view}.png`, kind: 'image', resolveUrl: resolver || (() => Promise.resolve(`url:${path}`)) }
  const props = { sessionId: session, toolCallId: id, file, result: JSON.stringify({ ...result, renders: renders || { [view]: path } }), fallback }
  return { component: env.mount(env.mediaContribution.data.render(props)), props }
}
const walk = node => !node || typeof node !== 'object' ? [] : [node, ...[].concat(node.props?.children || []).flatMap(walk)]
const text = node => !node ? '' : typeof node === 'string' || typeof node === 'number' ? String(node) : [].concat(node.props?.children || []).map(text).join(' ')
const paneNames = env => walk(env.pane.render()).filter(node => node.type === 'button' && node.props['data-view']).map(node => node.props['data-view'].toUpperCase().replace(/^(.+?)_DETAIL_/, '$1 · DETAIL: ').replaceAll('_', ' '))
const preview = env => walk(env.pane.render()).find(node => node.type === 'img' && node.props['data-preview'])

test('sheet exposes actual metadata and selectable available views only', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  const renders = { iso: '/r/iso.png', front_detail_contact: '/r/front.png', top: '/r/top.png' }
  const result = { step_file: '/models/bracket.step', source_sha256: 'a'.repeat(64), render_metadata: { front_detail_contact: { view: 'front', resolution: 1200, region: { label: 'contact', x_min: 0.4, y_min: 0.4, x_max: 0.6, y_max: 0.6 } } } }
  const iso = card(env, { renders, result }), front = card(env, { renders, result, view: 'front_detail_contact' })
  iso.component.render(); front.component.render(); await tick()
  let pane = env.pane.render(), body = text(pane)
  assert.match(body, /bracket\.step/); assert.match(body, /STEP/); assert.match(body, /a{12}/)
  assert.match(body, /2 of 3/); assert.match(body, /Ask the assistant to show the remaining views/)
  assert.deepEqual(paneNames(env), ['ISO', 'FRONT · DETAIL: CONTACT'])
  const button = walk(pane).find(node => node.type === 'button' && node.props['data-view'] === 'front_detail_contact')
  assert.equal(button.props.type, 'button'); button.props.onClick()
  pane = env.pane.render(); body = text(pane)
  assert.equal(preview(env).props.src, 'url:/r/front.png')
  assert.match(body, /1200/); assert.match(body, /contact/); assert.match(body, /0\.4/)
  assert.equal(walk(pane).find(node => node.type === 'button' && node.props['data-view'] === 'front_detail_contact').props['aria-pressed'], true)
})

test('selection and actual metadata do not leak between sessions or revisions', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one', 'two')); env.history.set('b', rows('b1'))
  const renders = { iso: '/one/iso.png', top: '/one/top.png' }
  for (const view of Object.keys(renders)) card(env, { renders, view, result: { step_file: '/models/old.step' } }).component.render()
  await tick(); walk(env.pane.render()).find(n => n.type === 'button' && n.props['data-view'] === 'top').props.onClick()
  assert.equal(preview(env).props.src, 'url:/one/top.png')
  const next = card(env, { id: 'two', view: 'iso', result: { mesh_file: '/models/new.stl' } }); next.component.render(); await tick()
  assert.equal(preview(env).props.src, 'url:/two/iso.png'); assert.match(text(env.pane.render()), /new\.stl/); assert.doesNotMatch(text(env.pane.render()), /old\.step/)
  card(env, { session: 'b', id: 'b1', view: 'top' }).component.render(); await tick(); env.stored.set('b')
  assert.equal(preview(env).props.src, 'url:/b1/top.png'); assert.doesNotMatch(text(env.pane.render()), /new\.stl/)
  env.stored.set('a'); assert.equal(preview(env).props.src, 'url:/two/iso.png')
})

test('zoom, view buttons and narrow-pane layout stay usable', async () => {
  const env = await setup({ nativeButtons: true }); env.stored.set('a'); env.history.set('a', rows('one', 'two'))
  const renders = { iso: '/one/iso.png', top: '/one/top.png' }
  for (const view of Object.keys(renders)) card(env, { renders, view }).component.render()
  await tick()
  let pane = env.pane.render()
  const strip = walk(pane).find(n => n.props?.['aria-label'] === 'Drawing views')
  assert.equal(strip.props.style.overflowX, 'auto'); assert.equal(strip.props.style.maxWidth, '100%')
  const zoom = walk(pane).find(n => n.type === 'button' && text(n) === 'Zoom 2×')
  assert.equal(preview(env).props.style.width, '100%'); zoom.props.onClick()
  assert.equal(preview(env).props.style.width, '200%')
  pane = env.pane.render(); assert.equal(walk(pane).find(n => n.type === 'button' && text(n) === 'Fit').props['aria-pressed'], true)
  walk(pane).find(n => n.type === 'button' && text(n) === 'Fit').props.onClick()
  assert.equal(preview(env).props.style.width, '100%')
  walk(env.pane.render()).find(n => n.type === 'button' && text(n) === 'Zoom 2×').props.onClick()
  card(env, { id: 'two', result: { mesh_file: 'C:\\\\models\\\\part.stl' } }).component.render(); await tick()
  assert.equal(preview(env).props.style.width, '100%'); assert.match(text(env.pane.render()), /part\.stl/)
})

test('zoomed drawing pans by pointer drag and keyboard; fit mode does not drag', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  card(env).component.render(); await tick()
  let pane = env.pane.render()
  const findViewport = () => walk(env.pane.render()).find(n => n.props?.['data-pan-viewport'])
  let viewport = findViewport()
  const target = {
    scrollLeft: 80, scrollTop: 60, setPointerCapture(id) { this.captured = id },
    releasePointerCapture(id) { this.released = id }, hasPointerCapture(id) { return this.captured === id },
  }
  assert.equal(viewport.props.tabIndex, 0)
  viewport.props.onPointerDown({ button: 0, pointerId: 3, clientX: 100, clientY: 90, currentTarget: target, preventDefault() {} })
  assert.equal(target.captured, undefined)
  walk(pane).find(n => n.type === 'button' && text(n) === 'Zoom 2×').props.onClick()
  viewport = findViewport()
  viewport.props.onPointerDown({ button: 0, pointerId: 3, clientX: 100, clientY: 90, currentTarget: target, preventDefault() {} })
  assert.equal(target.captured, 3)
  viewport.props.onPointerMove({ pointerId: 3, clientX: 70, clientY: 55, currentTarget: target })
  assert.equal(target.scrollLeft, 110); assert.equal(target.scrollTop, 95)
  viewport.props.onPointerUp({ pointerId: 3, currentTarget: target })
  assert.equal(target.released, 3)
  viewport.props.onPointerMove({ pointerId: 3, clientX: 0, clientY: 0, currentTarget: target })
  assert.equal(target.scrollLeft, 110); assert.equal(target.scrollTop, 95)
  let prevented = false
  viewport.props.onKeyDown({ key: 'ArrowRight', currentTarget: target, preventDefault() { prevented = true } })
  assert.equal(target.scrollLeft, 160); assert.equal(prevented, true)
  assert.match(text(env.pane.render()), /drag.*arrow keys/i)
})

test('loading, failed media, missing metadata and stale callbacks remain honest', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  const slow = deferred(), c = card(env, { resolver: () => slow.promise }); c.component.render(); await tick()
  assert.equal(env.pane.render().props.title, 'Loading drawing')
  slow.reject(Error('missing')); await tick(); assert.equal(env.pane.render().props.title, 'Drawing unavailable')
  const ok = card(env); ok.component.render(); await tick()
  assert.match(text(env.pane.render()), /Source model unavailable/)
  assert.doesNotMatch(text(env.pane.render()), /SHA-256|Resolution|ready|nozzle|material/i)
  assert.equal(preview(env).props.src, 'url:/one/iso.png')
  preview(env).props.onError(); assert.equal(env.pane.render().props.title, 'Drawing unavailable')
})

test('conflicting metadata for a reused call never mixes provenance', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  card(env, { result: { step_file: '/first.step' } }).component.render(); await tick()
  card(env, { result: { step_file: '/second.step' } }).component.render(); await tick()
  assert.deepEqual(paneNames(env), [])
})

test('detail payload labels and back view stay distinct in card and pane', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('detail'))
  const renders = { front_detail_face: '/preview_a_front_detail_face.png', back_detail_face: '/preview_a_back_detail_face.png' }
  const front = card(env, { id: 'detail', view: 'front_detail_face', renders })
  const back = card(env, { id: 'detail', view: 'back_detail_face', renders })
  front.component.render(); back.component.render(); await tick()
  assert.equal(front.component.render().props.children[1].props.children, 'FRONT · DETAIL: FACE')
  assert.equal(back.component.render().props.children[0].props.alt, 'back detail: face drawing')
  assert.deepEqual(paneNames(env), ['BACK · DETAIL: FACE', 'FRONT · DETAIL: FACE'])
})

test('registration is scoped and compatible with old desktop', async () => {
  const env = await setup()
  assert.equal(env.registrations.length, 2)
  assert.deepEqual(Array.from(env.mediaContribution.data.tools), ['vibecad_generate_preview_renders'])
  assert.equal((await setup({ media: false })).registrations.length, 1)
})

test('session focus, history order, mixed views and historical remount', async () => {
  const env = await setup(); env.stored.set('a')
  env.history.set('a', rows('old', 'new')); env.history.set('b', rows('b1'))
  const old = card(env, { id: 'old', view: 'front' })
  const renders = { iso: '/new/iso.png', top: '/new/top.png' }
  const current = card(env, { id: 'new', renders })
  const top = card(env, { id: 'new', view: 'top', renders })
  assert.equal(old.component.render(), 'BUILTIN'); current.component.render(); top.component.render()
  await tick(); assert.deepEqual(paneNames(env), ['ISO', 'TOP'])
  assert.equal(current.component.render().props.children[0].props.alt, 'iso drawing')
  old.component.unmount(); const oldAgain = card(env, { id: 'old', view: 'front' }); oldAgain.component.render(); await tick()
  assert.deepEqual(paneNames(env), ['ISO', 'TOP'])
  const other = card(env, { session: 'b', id: 'b1', view: 'right' }); other.component.render(); await tick()
  env.stored.set('b'); assert.deepEqual(paneNames(env), ['RIGHT'])
  env.stored.set('a'); assert.deepEqual(paneNames(env), ['ISO', 'TOP'])
  env.stored.set(null); env.runtime.set('b'); assert.deepEqual(paneNames(env), ['RIGHT'])
  env.runtime.set('missing'); assert.deepEqual(paneNames(env), [])
  assert.ok(env.requests.every(([method]) => method === 'session.history'))
})

test('latest candidate does not inherit old views while loading or after rejection', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('old', 'new'))
  const old = card(env, { id: 'old', view: 'front' }); old.component.render(); await tick()
  assert.deepEqual(paneNames(env), ['FRONT'])
  const slow = deferred(), newer = card(env, { id: 'new', resolver: () => slow.promise }); newer.component.render(); await tick()
  assert.deepEqual(paneNames(env), [])
  slow.reject(new Error('unavailable')); await tick()
  assert.equal(newer.component.render(), 'BUILTIN'); assert.deepEqual(paneNames(env), [])
})

test('out-of-order history and URL completion, cleanup and fallback', async () => {
  const env = await setup(); env.stored.set('a')
  const one = deferred(), two = deferred(); let count = 0
  env.setRequest(() => (++count === 1 ? one.promise : two.promise))
  const slowUrl = deferred(), first = card(env, { id: 'old', resolver: () => slowUrl.promise })
  first.component.render(); await tick()
  const second = card(env, { id: 'new' }); second.component.render(); await tick()
  two.resolve({ messages: rows('old', 'new') }); await tick()
  one.resolve({ messages: rows('old') }); slowUrl.resolve('old-url'); await tick()
  // URL completion causes another history query: use a fresh snapshot.
  assert.deepEqual(paneNames(env), ['ISO'])
  assert.equal(preview(env).props.src, 'url:/new/iso.png')
  const gone = deferred(), unmounted = card(env, { id: 'gone', resolver: () => gone.promise }); unmounted.component.render(); unmounted.component.unmount(); gone.resolve('gone-url'); await tick()
  assert.equal(unmounted.component.render(), 'BUILTIN')
})

test('ambiguous calls, missing identity, failed history and non-images fail safely', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('same', 'same'))
  const c = card(env, { id: 'same' }); c.component.render(); await tick(); assert.deepEqual(paneNames(env), [])
  const unidentified = card(env, { id: '', session: null }); unidentified.component.render(); await tick(); assert.equal(unidentified.component.render().type, 'figure')
  env.setRequest(async () => { throw new Error('offline') })
  const other = card(env, { id: 'other' }); other.component.render(); await tick(); assert.deepEqual(paneNames(env), [])
  const notImage = { ...other.props, file: { ...other.props.file, kind: 'video', resolveUrl: () => { throw Error('should not resolve') } } }
  assert.equal(other.component.render(notImage), 'BUILTIN')
  const node = c.component.render(); node.props.children[0].props.onError(); assert.equal(c.component.render(), 'BUILTIN')
})

test('identity and changed paths cannot retain a stale inline URL', async () => {
  const env = await setup(); env.stored.set('stored'); env.runtime.set('runtime')
  env.history.set('runtime', rows('one'))
  const original = card(env, { session: 'stored' }); original.component.render(); await tick()
  assert.equal(original.component.render().props.children[0].props.src, 'url:/one/iso.png')
  assert.ok(env.requests.some(([, params]) => params.session_id === 'runtime'))
  const nextUrl = deferred()
  const updated = { ...original.props, file: { ...original.props.file, path: '/next.png', resolveUrl: () => nextUrl.promise }, result: { renders: { front: '/next.png' } } }
  assert.equal(original.component.render(updated), 'BUILTIN')
  nextUrl.resolve('new-url'); await tick()
  const next = original.component.render(updated)
  assert.equal(next.props.children[0].props.src, 'new-url')
  assert.equal(next.props.children[0].props.alt, 'front drawing')
  // Same call id carrying a different result cannot be merged as a sheet.
  assert.deepEqual(paneNames(env), [])
})

test('empty or invalid URLs retain the built-in player and invalid history clears pane', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  const ok = card(env); ok.component.render(); await tick(); assert.deepEqual(paneNames(env), ['ISO'])
  env.setRequest(async () => ({}))
  const empty = card(env, { id: 'two', resolver: async () => '' }); empty.component.render(); await tick()
  assert.equal(empty.component.render(), 'BUILTIN'); assert.deepEqual(paneNames(env), [])
})

test('a deferred (bridged) tool row is recognised as the tool it ran', async () => {
  // Every deferred invocation is stored as the "tool_call" bridge, so a pane
  // that matches on the row's own name never sees the tool it drew.
  const env = await setup(); env.stored.set('a'); env.history.set('a', bridged('one'))
  const c = card(env, { id: 'one' }); c.component.render(); await tick()
  assert.deepEqual(paneNames(env), ['ISO'])
})

test('a bridge that ran another tool is not claimed, and a batch is not split', async () => {
  const env = await setup(); env.stored.set('a')
  env.history.set('a', [{ role: 'tool', name: 'tool_call', tool_call_id: 'other', args: { calls: [{ name: 'terminal', arguments: {} }] } }])
  const c = card(env, { id: 'one' }); c.component.render(); await tick()
  assert.deepEqual(paneNames(env), [])
  // A multi-entry batch belongs to the bridge, not to this plugin: no single
  // entry may be claimed, or the pane would show a sheet it cannot attribute.
  env.history.set('a', [{ role: 'tool', name: 'tool_call', tool_call_id: 'batch', args: { calls: [
    { name: 'vibecad_generate_preview_renders', arguments: {} },
    { name: 'terminal', arguments: {} },
  ] } }])
  env.pane.render(); await tick()
  assert.deepEqual(paneNames(env), [])
})

test('fuses full-frame and detail calls sharing the same verified 64-hex source_sha256', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', bridged('full', 'detail1', 'detail2'))
  const hash = 'b'.repeat(64)
  const meta = { step_file: '/models/statue.step', source_sha256: hash }
  const fullRenders = { iso: '/r/iso.png', front: '/r/front.png', top: '/r/top.png' }
  for (const view of Object.keys(fullRenders)) card(env, { id: 'full', view, renders: fullRenders, result: meta }).component.render()
  card(env, { id: 'detail1', view: 'front_detail_face', renders: { front_detail_face: '/r/face.png' }, result: meta }).component.render()
  card(env, { id: 'detail2', view: 'back_detail_hand', renders: { back_detail_hand: '/r/hand.png' }, result: meta }).component.render()
  await tick()
  assert.deepEqual(paneNames(env), ['ISO', 'TOP', 'FRONT', 'BACK · DETAIL: HAND', 'FRONT · DETAIL: FACE'])
  assert.match(text(env.pane.render()), /5 of 5/)
})

test('virtualized card unmount preserves ready sheet views and bounds session cache', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('one'))
  const mounted = card(env, { id: 'one', view: 'iso', result: { step_file: '/models/keep.step', source_sha256: 'c'.repeat(64) } })
  mounted.component.render(); await tick()
  assert.deepEqual(paneNames(env), ['ISO'])
  const callsBeforeUnmount = env.requests.length
  mounted.component.unmount(); await tick()
  assert.deepEqual(paneNames(env), ['ISO'])
  assert.equal(env.requests.length, callsBeforeUnmount)

  for (let i = 0; i < 15; i++) {
    const sid = `bg-${i}`
    env.history.set(sid, rows(`call-${i}`))
    card(env, { session: sid, id: `call-${i}`, view: 'top' }).component.render()
  }
  await tick()
  assert.deepEqual(paneNames(env), ['ISO'])
})

test('revision switcher and Compare prev toggle between verified revisions honestly', async () => {
  const env = await setup(); env.stored.set('a'); env.history.set('a', rows('rev1', 'rev2'))
  card(env, { id: 'rev1', view: 'iso', renders: { iso: '/v1/iso.png' }, result: { step_file: '/models/v1.step', source_sha256: '1'.repeat(64) } }).component.render()
  card(env, { id: 'rev2', view: 'iso', renders: { iso: '/v2/iso.png' }, result: { step_file: '/models/v2.step', source_sha256: '2'.repeat(64) } }).component.render()
  await tick()
  assert.equal(preview(env).props.src, 'url:/v2/iso.png')
  assert.doesNotMatch(text(env.pane.render()), /v1\.step/)

  const compare = walk(env.pane.render()).find(n => n.type === 'button' && n.props['data-compare'])
  assert.ok(compare)
  compare.props.onClick()
  let pane = env.pane.render()
  assert.equal(preview(env).props.src, 'url:/v1/iso.png')
  assert.match(text(pane), /Older revision/i)

  walk(pane).find(n => n.type === 'button' && n.props['data-compare']).props.onClick()
  assert.equal(preview(env).props.src, 'url:/v2/iso.png')
})

test('title block renders geometry_summary, Z-datum warning, 4x zoom, keyboard view switch and OS actions', async () => {
  const revealed = [], copied = []
  const env = await setup({
    os: { revealPath: async p => { revealed.push(p); return true }, writeClipboard: async t => { copied.push(t); return true } },
  })
  env.stored.set('a'); env.history.set('a', rows('one'))
  const renders = { iso: '/r/iso.png', left: '/r/left.png' }
  const result = {
    step_file: '/models/enclosure.step',
    source_sha256: 'd'.repeat(64),
    geometry_summary: { bbox_size_mm: { x: 120.5, y: 80, z: 45.25 }, z_min_mm: -1.5, part_count: 2, triangle_count: 480 },
  }
  for (const view of Object.keys(renders)) card(env, { renders, view, result }).component.render()
  await tick()
  let pane = env.pane.render(), body = text(pane)
  assert.match(body, /120\.5 × 80 × 45\.25 mm/)
  assert.match(body, /Zmin -1\.5 mm/)
  assert.match(body, /off Z=0/i)

  await walk(pane).find(n => n.type === 'button' && n.props['data-action'] === 'reveal-model').props.onClick()
  await walk(pane).find(n => n.type === 'button' && n.props['data-action'] === 'copy-hash').props.onClick()
  assert.deepEqual(revealed, ['/models/enclosure.step'])
  assert.ok(copied.includes('d'.repeat(64)) || env.clipboard.includes('d'.repeat(64)))

  walk(pane).find(n => n.type === 'button' && text(n) === 'Zoom 4×').props.onClick()
  assert.equal(preview(env).props.style.width, '400%')
  walk(env.pane.render()).find(n => n.type === 'button' && text(n) === 'Fit').props.onClick()
  assert.equal(preview(env).props.style.width, '100%')

  const section = env.pane.render()
  section.props.onKeyDown({ key: ']', metaKey: true, preventDefault() {} })
  assert.equal(preview(env).props.src, 'url:/r/iso.png')
  section.props.onKeyDown({ key: ']', preventDefault() {} })
  assert.equal(preview(env).props.src, 'url:/r/left.png')
})

test('interactive drag-to-crop region loupe computes normalized bounds and inserts composer prompt', async () => {
  const inserted = []
  const env = await setup({
    composer: { insertText: async (sid, prompt) => { inserted.push([sid, prompt]); return true } },
  })
  env.stored.set('a'); env.history.set('a', rows('one'))
  card(env, { view: 'front', renders: { front: '/r/front.png' }, result: { step_file: '/models/clip.step', source_sha256: 'e'.repeat(64) } }).component.render()
  await tick()

  walk(env.pane.render()).find(n => n.type === 'button' && n.props['data-action'] === 'toggle-crop').props.onClick()
  const findViewport = () => walk(env.pane.render()).find(n => n.props?.['data-pan-viewport'])
  const boxTarget = {
    getBoundingClientRect: () => ({ left: 100, top: 200, width: 200, height: 200 }),
    setPointerCapture() {}, releasePointerCapture() {}, hasPointerCapture: () => true,
  }
  findViewport().props.onPointerDown({ button: 0, pointerId: 7, clientX: 150, clientY: 220, currentTarget: boxTarget, preventDefault() {} })
  findViewport().props.onPointerMove({ pointerId: 7, clientX: 250, clientY: 320, currentTarget: boxTarget })
  findViewport().props.onPointerUp({ pointerId: 7, currentTarget: boxTarget })

  const pane = env.pane.render()
  assert.ok(walk(pane).find(n => n.props?.['data-region-box']))
  await walk(pane).find(n => n.type === 'button' && n.props['data-action'] === 'insert-crop-prompt').props.onClick()
  assert.equal(inserted.length, 1)
  assert.equal(inserted[0][0], 'a')
  assert.match(inserted[0][1], /vibecad_generate_preview_renders/)
  assert.match(inserted[0][1], /"x_min":0\.25.*"y_min":0\.1.*"x_max":0\.75.*"y_max":0\.6/)
})
