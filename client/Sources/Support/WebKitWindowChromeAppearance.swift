import AppKit

enum WebKitWindowChromeAppearance {
    static let frameInset: CGFloat = 4
    static let cornerRadius: CGFloat = 16

    @MainActor
    static func apply(to window: NSWindow) {
        window.hasShadow = false
        window.isOpaque = false
        window.backgroundColor = .clear
        window.appearance = NSAppearance(named: .aqua)

        guard let contentView = window.contentView else { return }
        contentView.wantsLayer = true
        contentView.layer?.backgroundColor = NSColor.clear.cgColor
        contentView.layer?.cornerRadius = cornerRadius
        contentView.layer?.masksToBounds = false
    }
}
