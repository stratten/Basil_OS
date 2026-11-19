import './window-move-handle.css'

/**
 * Two hairlines that say the whole header drags the window. Every window header that the native `WindowDragAreaView` lets you drag renders this as the first child of its header element, and that header carries the `window-move-host` class so the grip can center itself on it and show when the header is hovered or holds focus.
 *
 * It only advertises the native drag area, so it takes no pointer events, and it sits out of the header's flow so nothing shifts when it appears.
 */
export function WindowMoveHandle() {
  return (
    <span className="window-move-handle" data-window-move-handle="true" aria-hidden="true">
      <i />
      <i />
    </span>
  )
}
