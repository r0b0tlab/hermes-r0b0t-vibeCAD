import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const latestViews = sdk.atom({})
const VIEW_ORDER = ['iso', 'top', 'front', 'right', 'bottom']

function asObject(value) {
  if (value && typeof value === 'object') return value
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
      return null
    }
  }
  return null
}

function viewName(file, result) {
  const renders = asObject(result)?.renders
  if (!renders || typeof renders !== 'object') return file.name.replace(/^preview_/, '').replace(/\.png$/i, '')
  for (const name of Object.keys(renders)) {
    if (renders[name] === file.path) return name
  }
  return file.name.replace(/^preview_/, '').replace(/\.png$/i, '')
}

function orderedNames(views) {
  return Object.keys(views).sort((a, b) => {
    const ia = VIEW_ORDER.indexOf(String(a).toLowerCase())
    const ib = VIEW_ORDER.indexOf(String(b).toLowerCase())
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
}

function DrawingCard({ file, result, fallback }) {
  const [src, setSrc] = useState(null)
  const label = viewName(file, result)
  const path = file && file.path
  useEffect(() => {
    if (!file || typeof file.resolveUrl !== 'function') return undefined
    let live = true
    file.resolveUrl().then(
      (url) => {
        if (!live) return
        setSrc(url)
        const current = latestViews.get()
        latestViews.set({ ...current, [label]: { url, name: file.name } })
      },
      () => live && setSrc(''),
    )
    return () => {
      live = false
    }
  }, [file, label, path])
  if (!file || file.kind !== 'image' || !src) return fallback
  return jsxs('figure', {
    style: {
      margin: 0,
      maxWidth: 420,
      border: '1px solid var(--ui-stroke-secondary)',
      borderRadius: 8,
      overflow: 'hidden',
    },
    children: [
      jsx('img', { alt: label, src, style: { display: 'block', width: '100%', height: 'auto' } }),
      jsx('figcaption', {
        style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.06em', padding: '6px 8px' },
        children: String(label).toUpperCase(),
      }),
    ],
  })
}

function DrawingPane() {
  const views = sdk.useValue(latestViews)
  const names = orderedNames(views)
  if (!names.length) {
    return jsx(sdk.EmptyState, {
      title: 'No drawing yet',
      description: 'Generate previews. Labeled drawings appear here and inline in the chat.',
    })
  }
  return jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 12, padding: 12 },
    children: names.map((name) =>
      jsxs('figure', {
        key: name,
        style: { margin: 0 },
        children: [
          jsx('figcaption', {
            style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.06em' },
            children: String(name).toUpperCase(),
          }),
          jsx('img', { alt: name, src: views[name].url, style: { display: 'block', width: '100%', height: 'auto' } }),
        ],
      }),
    ),
  })
}

export default {
  id: 'hermes-r0b0t-vibeCAD',
  name: 'vibeCAD drawings',
  register(ctx) {
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') {
      ctx.register({
        id: 'preview-drawings',
        area: sdk.TOOL_MEDIA_RENDERER_AREA,
        data: {
          tools: ['vibecad_generate_preview_renders'],
          render: (props) => jsx(DrawingCard, props),
        },
      })
    }
    ctx.register({
      id: 'drawing-pane',
      area: 'panes',
      title: 'vibeCAD',
      data: { placement: 'right', width: '300px' },
      render: () => jsx(DrawingPane, {}),
    })
  },
}
