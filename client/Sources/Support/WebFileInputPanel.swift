import AppKit
import WebKit

/// Answers a web page's file input with a native open panel. WKWebView shows nothing for `<input type="file">` unless its `WKUIDelegate` implements `runOpenPanelWith`, so each web host that offers a file chooser forwards that delegate call here.
@MainActor
enum WebFileInputPanel {
    static func present(
        parameters: WKOpenPanelParameters,
        over webView: WKWebView,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.applyBasilThemedAppearance()

        if let window = webView.window {
            panel.beginSheetModal(for: window) { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
        } else {
            panel.beginAboveFloatingWindows { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
        }
    }
}
