import Foundation
@preconcurrency import WebKit

extension WKWebView {
    /// Calls `function(event)` in the page's JavaScript world with one JSON-compatible event value.
    ///
    /// The value is passed through `callAsyncJavaScript` as a named argument, so it is never spliced into a script string and needs no escaping. Every React-hosted Basil surface that exposes an `onEvent`-style entry point uses this call; each surface keeps a small `callJS` wrapper that supplies its own log tag. A failed call is logged in DEBUG builds only.
    ///
    /// - Parameters:
    ///   - function: The JavaScript function expression to call, for example `window.basilMemoriesSettings && window.basilMemoriesSettings.onEvent`.
    ///   - event: The single argument handed to the function.
    ///   - logTag: The bracketed prefix of the DEBUG failure message, for example `MEMORIES_SETTINGS_WEB`.
    ///   - logContext: The `DevLogger` context for the DEBUG failure message.
    func callBasilEventHandler(_ function: String, event: Any, logTag: String, logContext: String) {
        callAsyncJavaScript(
            "\(function)(event)",
            arguments: ["event": event],
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error(
                    "[\(logTag)] callAsyncJavaScript failed for \(function): \(error)",
                    context: logContext
                )
                #endif
            }
        }
    }
}
