import AppKit
@preconcurrency import WebKit

@MainActor
func applyWebViewWindowAppearance(for panel: NSWindow) {
    WebKitWindowChromeAppearance.apply(to: panel)
}

@MainActor
func fadeInWebViewContent(_ webView: WKWebView) {
    NSAnimationContext.runAnimationGroup { context in
        context.duration = 0.25
        context.timingFunction = CAMediaTimingFunction(name: .easeIn)
        webView.animator().alphaValue = 1.0
    }
}

@MainActor
final class WebViewReadyGate {
    private var didDeliverReady = false

    func deliverReady(_ action: () -> Void) {
        guard !didDeliverReady else { return }
        didDeliverReady = true
        action()
    }
}
