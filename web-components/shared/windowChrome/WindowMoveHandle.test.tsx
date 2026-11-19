import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WindowMoveHandle } from './WindowMoveHandle'

describe('WindowMoveHandle', () => {
  it('is two bare hairlines with no box and no dots, hidden from assistive technology', () => {
    const markup = renderToStaticMarkup(<WindowMoveHandle />)

    expect(markup).toBe('<span class="window-move-handle" data-window-move-handle="true" aria-hidden="true"><i></i><i></i></span>')
  })
})
