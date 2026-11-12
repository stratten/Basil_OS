import AppKit
import XCTest
@testable import BasilClient

/// Cmd+W and Cmd+M must act on the window the keystroke was delivered to, and on no other window that happens to use the same helper.
@MainActor
final class WindowKeyboardShortcutsTests: XCTestCase {
    private var windows: [NSWindow] = []
    private var shortcuts: [WindowKeyboardShortcuts] = []

    override func tearDown() {
        shortcuts.forEach { $0.cleanup() }
        shortcuts.removeAll()
        windows.forEach { $0.orderOut(nil) }
        windows.removeAll()
        super.tearDown()
    }

    private func makeWindow() -> NSWindow {
        _ = NSApplication.shared
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 200, height: 120),
            styleMask: [.borderless, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.orderFrontRegardless()
        shortcuts.append(WindowKeyboardShortcuts(window: window))
        windows.append(window)
        return window
    }

    private func sendKeyDown(_ character: String, to window: NSWindow, modifiers: NSEvent.ModifierFlags = .command) {
        let event = NSEvent.keyEvent(
            with: .keyDown,
            location: .zero,
            modifierFlags: modifiers,
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber,
            context: nil,
            characters: character,
            charactersIgnoringModifiers: character,
            isARepeat: false,
            keyCode: 13
        )
        guard let event else {
            XCTFail("could not build a key event")
            return
        }
        NSApp.sendEvent(event)
    }

    private func closeCount(of window: NSWindow, while body: () -> Void) -> Int {
        var count = 0
        let observer = NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: nil) { _ in
            count += 1
        }
        body()
        NotificationCenter.default.removeObserver(observer)
        return count
    }

    func testCommandWClosesOnlyTheWindowTheKeystrokeWasDeliveredTo() throws {
        let first = makeWindow()
        let second = makeWindow()
        try XCTSkipIf(first.windowNumber <= 0 || second.windowNumber <= 0, "this environment has no window server")

        let closedFirst = closeCount(of: first) {
            let closedSecond = closeCount(of: second) {
                sendKeyDown("w", to: second)
            }
            XCTAssertEqual(closedSecond, 1, "the window that received Cmd+W should close")
        }

        XCTAssertEqual(closedFirst, 0, "a different window that uses the same helper must not close")
    }

    func testCommandWAimedAtTheFirstWindowDoesNotCloseTheSecond() throws {
        let first = makeWindow()
        let second = makeWindow()
        try XCTSkipIf(first.windowNumber <= 0 || second.windowNumber <= 0, "this environment has no window server")

        let closedSecond = closeCount(of: second) {
            let closedFirst = closeCount(of: first) {
                sendKeyDown("w", to: first)
            }
            XCTAssertEqual(closedFirst, 1)
        }

        XCTAssertEqual(closedSecond, 0)
    }

    /// The reported bug: the Agent Task Result window is a "main" window, so it closed on Cmd+W even when the window in front was a different one.
    func testAWindowThatIsOnlyMainDoesNotAnswerCommandWForAnotherWindow() throws {
        let mainOnly = makeWindow()
        let target = makeWindow()
        try XCTSkipIf(mainOnly.windowNumber <= 0 || target.windowNumber <= 0, "this environment has no window server")
        mainOnly.makeMain()
        try XCTSkipUnless(mainOnly.isMainWindow && !target.isKeyWindow, "this environment would not make the window main")

        let closedMainOnly = closeCount(of: mainOnly) {
            let closedTarget = closeCount(of: target) {
                sendKeyDown("w", to: target)
            }
            XCTAssertEqual(closedTarget, 1, "the window that received Cmd+W should close")
        }

        XCTAssertEqual(closedMainOnly, 0, "a window that is only main must not close for a keystroke aimed at another window")
    }

    func testOtherKeysAndModifiersDoNotCloseTheWindow() throws {
        let window = makeWindow()
        try XCTSkipIf(window.windowNumber <= 0, "this environment has no window server")

        let closed = closeCount(of: window) {
            sendKeyDown("w", to: window, modifiers: [])
            sendKeyDown("q", to: window)
        }

        XCTAssertEqual(closed, 0)
    }
}
