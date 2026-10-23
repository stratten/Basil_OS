import Foundation
@preconcurrency import WebKit

/// Serves local file content over a custom URL scheme so a `WKWebView` can
/// render a static HTML artifact (plus its relative CSS/JS/image references)
/// with scripts enabled, which a `file://` load or a sandboxed `srcDoc`
/// cannot do.
///
/// `allowedDirectory` scopes which files are reachable. Detached preview
/// windows (`AgentTaskLocalWebPreviewWindowHost`) construct a fresh instance
/// per open, scoped to that artifact's own directory. `AgentTaskResultWebView`
/// is a single long-lived webview shared across many agent tasks/artifacts,
/// and WebKit only allows registering a `WKURLSchemeHandler` before a
/// `WKWebView` is created -- it cannot swap handlers on an existing webview's
/// configuration. So that call site registers one instance scoped to the
/// filesystem root (`/`) instead of a per-artifact directory. The root-scope
/// case is handled explicitly below since it is not equivalent to "any
/// directory scoping": with `allowedDirectory.path == "/"`, `allowedDirectory.path + "/"`
/// is `"//"`, which no real absolute path starts with, so the containment
/// check would otherwise reject every request.
final class LocalPreviewFileSchemeHandler: NSObject, WKURLSchemeHandler {
    private let allowedDirectory: URL

    init(allowedDirectory: URL) {
        self.allowedDirectory = allowedDirectory.standardizedFileURL
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let requestURL = urlSchemeTask.request.url else {
            urlSchemeTask.didFailWithError(URLError(.badURL))
            return
        }
        let relativePath = requestURL.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let fileURL = allowedDirectory.appendingPathComponent(relativePath).standardizedFileURL
        guard fileURL.path == allowedDirectory.path
            || fileURL.path.hasPrefix(allowedDirectory.path + "/")
            || allowedDirectory.path == "/",
              let data = try? Data(contentsOf: fileURL) else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let response = HTTPURLResponse(
            url: requestURL,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: [
                "Access-Control-Allow-Origin": "*",
                "Content-Length": String(data.count),
                "Content-Type": "\(mimeType(for: fileURL)); charset=utf-8",
            ]
        )
        guard let response else {
            urlSchemeTask.didFailWithError(URLError(.cannotParseResponse))
            return
        }
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func mimeType(for fileURL: URL) -> String {
        switch fileURL.pathExtension.lowercased() {
        case "css": return "text/css"
        case "html", "htm": return "text/html"
        case "js", "mjs": return "text/javascript"
        case "json": return "application/json"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "svg": return "image/svg+xml"
        case "webp": return "image/webp"
        default: return "application/octet-stream"
        }
    }
}

func allowsLocalPreviewNavigation(_ url: URL, mode: String) -> Bool {
    if url.scheme == "basil-preview-file" { return mode == "static" }
    return mode == "devServer" && url.scheme == "http" && url.host == "127.0.0.1"
}
