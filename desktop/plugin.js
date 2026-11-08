import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const latestViews = sdk.atom({})

function viewName(file, result) {
  const renders = result && typeof result === 'object' ? result.renders : null
  if (!renders || typeof renders !== 'object') return file.name
  for (const name of Object.keys(renders)) {
    if (renders[name] === file.path) return name
  }
  return file.name
}

function DrawingCard({ file, result, fallback }) {
  const [src, setSrc] = useState(null)
  const label = viewName(file, result)
  useEffect(() => {
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
  }, [file, label])
  if (file.kind !== 'image' || src === '') return fallback
  return jsxs('figure', {
    style: { margin: 0 },
    children: [
      jsx('figcaption', {
        style: { color: 'var(--ui-text-secondary)', fontSize: 12, letterSpacing: '0.04em' },
        children: String(label).toUpperCase(),
      }),
      src ? jsx('img', { alt: label, src, style: { display: 'block', maxWidth: '100%', height: 'auto' } }) : null,
    ],
  })
}

function DrawingPane() {
  const views = sdk.useValue(latestViews)
  const names = Object.keys(views)
  if (!names.length) {
    return jsx(sdk.EmptyState, {
      title: 'No drawing yet',
      description: 'Generate previews and emit their MEDIA lines. This pane fills from those inline drawings.',
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
            style: { color: 'var(--ui-text-secondary)', fontSize: 12 },
            children: name.toUpperCase(),
          }),
          jsx('img', { alt: name, src: views[name].url, style: { display: 'block', maxWidth: '100%', height: 'auto' } }),
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
      data: { placement: 'right', width: '280px' },
      render: () => jsx(DrawingPane, {}),
    })
  },
}
