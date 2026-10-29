import AppKit

final class FilePreviewDragAreaView: NSView {
    private let leftControlWidth: CGFloat = 96
    private let rightActionWidth: CGFloat = 270

    override func hitTest(_ point: NSPoint) -> NSView? {
        let local = point
        guard bounds.contains(local) else { return nil }
        if local.x < leftControlWidth || local.x > bounds.width - rightActionWidth {
            return nil
        }
        return self
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseDown(with event: NSEvent) {
        window?.makeKey()
        window?.performDrag(with: event)
    }
}
