import AppKit
@preconcurrency import WebKit

@MainActor
enum SetupWindowDragAreaInstaller {
    static let headerHeight: CGFloat = 44

    static func install(in webView: WKWebView) {
        let dragView = WindowDragAreaView(
            leadingInteractiveWidth: 84,
            trailingInteractiveWidth: 0
        )
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(
                equalToConstant: WebKitWindowChromeAppearance.frameInset + headerHeight
            ),
        ])
    }
}
