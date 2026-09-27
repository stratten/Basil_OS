import AppKit

/// A `CustomBorderlessPanel` that closes on Cmd+W.
///
/// Borderless panels have no title bar / close button and no menu wiring, so
/// AppKit's standard `performClose:` key equivalent never reaches them -- and
/// `performClose(_:)` itself would just beep and refuse, since the style mask
/// has no `.closable` button. This subclass intercepts Command-"W" and calls
/// `close()`, which still posts `windowWillClose` so the existing delegate
/// cleanup runs. `windowShouldClose(_:)` is honored when the delegate implements
/// it. Scoped to the meeting and analysis windows; the shared base class used by
/// other widgets is intentionally left unchanged.
final class ClosableBorderlessPanel: CustomBorderlessPanel {
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.type == .keyDown,
           event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
           event.charactersIgnoringModifiers?.lowercased() == "w" {
            // Borderless panels lack a close button, so performClose(_:) would
            // beep. close() reliably closes and still fires windowWillClose.
            let shouldClose = delegate?.windowShouldClose?(self) ?? true
            if shouldClose {
                close()
            }
            return true
        }
        return super.performKeyEquivalent(with: event)
    }
}
