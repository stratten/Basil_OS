import Foundation
@preconcurrency import WebKit

extension WKWebView {
    /// Calls `function(arg0, arg1, ...)` in the page with each argument serialized to a JSON literal.
    ///
    /// Use this for surfaces whose JavaScript entry point takes several arguments or whose argument can be a bare string, number, or boolean. Surfaces with a single `onEvent` argument use `callBasilEventHandler` instead.
    ///
    /// Every argument is checked with `JSONSerialization.isValidJSONObject` before it is serialized, because `JSONSerialization.data(withJSONObject:)` raises an Objective-C exception for an invalid value (a `NaN`, a `Date`, a non-string dictionary key) and `try?` does not catch it. If any argument is not valid JSON the whole call is dropped, so a later argument can never shift into an earlier parameter, and the reason is reported.
    ///
    /// - Parameters:
    ///   - function: The JavaScript function expression to call. It may be a guarded expression such as `window.basilPanel && window.basilPanel.onEvent`.
    ///   - args: The arguments, each a JSON-compatible value (a dictionary, an array, a string, a number, a boolean, or `NSNull`).
    ///   - logTag: The bracketed prefix of the DEBUG log message, for example `MeetingDetectedMiniPanelWebView`.
    ///   - logContext: The `DevLogger` context for the DEBUG log message.
    ///   - onFailure: Optional hook called with a one-line description when the call is dropped or the page reports a JavaScript error. It runs in every build configuration.
    func callBasilFunction(
        _ function: String,
        args: [Any],
        logTag: String,
        logContext: String,
        onFailure: ((String) -> Void)? = nil
    ) {
        var literals: [String] = []
        for (index, value) in args.enumerated() {
            guard let literal = Self.jsonLiteral(for: value) else {
                let message = "JavaScript call \(function) dropped: argument \(index) is not JSON-serializable"
                #if DEBUG
                DevLogger.shared.error("[\(logTag)] \(message)", context: logContext)
                #endif
                onFailure?(message)
                return
            }
            literals.append(literal)
        }

        evaluateJavaScript("\(function)(\(literals.joined(separator: ", ")))") { _, error in
            guard let error else { return }
            #if DEBUG
            DevLogger.shared.error(
                "[\(logTag)] evaluateJavaScript failed for \(function): \(error)",
                context: logContext
            )
            #endif
            onFailure?("JavaScript call \(function) failed: \(error.localizedDescription)")
        }
    }

    /// Returns the JSON text for one value, or `nil` when the value cannot be represented as JSON.
    ///
    /// The value is wrapped in an array for the validity check because `isValidJSONObject` rejects a bare string or number at the top level even though `.fragmentsAllowed` can serialize it.
    static func jsonLiteral(for value: Any) -> String? {
        guard JSONSerialization.isValidJSONObject([value]),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]),
              let literal = String(data: data, encoding: .utf8) else {
            return nil
        }
        return literal
    }
}
