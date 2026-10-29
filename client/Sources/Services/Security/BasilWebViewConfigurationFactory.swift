import Foundation
import WebKit

/// Builds every Basil web view configuration so bundled pages can authenticate to the local backend.
@MainActor
enum BasilWebViewConfigurationFactory {
    nonisolated static let credentialMessageHandlerName = "basilBackendCredentials"

    /// - Parameter blueprintReveal: Whether the page should play the blueprint reveal as it appears. Defaults to the user's setting. Embedded panes, which have no window chrome of their own, pass `false`.
    /// - Parameter textScale: The app-wide text size the page starts at, applied as `--text-scale` before its first paint. Defaults to the user's setting.
    static func makeConfiguration(
        credentialStore: BackendCredentialStore = .shared,
        backendPortProvider: @escaping @MainActor () -> Int = { APIClient.shared.currentPort },
        trustedAssetRootPath: String? = Bundle.main.resourceURL?.standardizedFileURL.path,
        blueprintReveal: Bool = AestheticSystem.blueprintReveal,
        textScale: Double = AestheticSystem.textScale
    ) -> WKWebViewConfiguration {
        let configuration = WKWebViewConfiguration()
        applyBundledPageAccess(to: configuration)
        // The blueprint reveal has to hide a window from its very first paint, so the flag is set before the page's own scripts run rather than arriving later in a bridge event.
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: BlueprintRevealPolicy.firstPaintScriptSource(enabled: blueprintReveal),
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        // The text size has to be right from the first paint too, or every window would flash at 100% before the bridge theme arrives.
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: TextScaleStep.firstPaintScriptSource(scale: textScale),
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        guard let trustedAssetRootPath,
              let source = backendAuthorizationScriptSource(
                  initialWebviewToken: credentialStore.webviewToken,
                  initialBackendPort: backendPortProvider(),
                  trustedAssetRootPath: trustedAssetRootPath
              ) else {
            return configuration
        }
        configuration.userContentController.addScriptMessageHandler(
            BackendCredentialMessageHandler(
                credentialStore: credentialStore,
                backendPortProvider: backendPortProvider,
                trustedAssetRootPath: trustedAssetRootPath
            ),
            contentWorld: .page,
            name: credentialMessageHandlerName
        )
        configuration.userContentController.addUserScript(
            WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        )
        return configuration
    }

    /// Bundled pages are Vite module scripts loaded from `file://`, which WebKit will not run without `allowFileAccessFromFileURLs`.
    /// `allowUniversalAccessFromFileURLs` is deliberately never set: Agent Task previews render agent-produced HTML from `file://` URLs inside these web views, and that flag would let such a page read any local file and call any origin. With file access enabled WebKit sends `Origin: file://` from bundled pages, so the backend's CORS allowlist must include `file://` (see `main.py`) or every bundled page's preflight fails with a 400.
    /// The Web Inspector is enabled only in debug builds so a shipped app cannot be inspected through Safari's Develop menu.
    static func applyBundledPageAccess(to configuration: WKWebViewConfiguration) {
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        #if DEBUG
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        #endif
    }

    nonisolated static func normalizedTrustedRoot(_ trustedAssetRootPath: String) -> String {
        trustedAssetRootPath.hasSuffix("/") ? trustedAssetRootPath : trustedAssetRootPath + "/"
    }

    nonisolated static func backendAuthorizationScriptSource(
        initialWebviewToken: String?,
        initialBackendPort: Int,
        trustedAssetRootPath: String?
    ) -> String? {
        guard (1...65_535).contains(initialBackendPort),
              let trustedAssetRootPath, !trustedAssetRootPath.isEmpty else {
            return nil
        }
        let initialTokenLiteral: String
        if let initialWebviewToken, BackendCredentials.isValidToken(initialWebviewToken),
           let literal = javaScriptStringLiteral(initialWebviewToken) {
            initialTokenLiteral = literal
        } else {
            initialTokenLiteral = "null"
        }
        guard let rootLiteral = javaScriptStringLiteral(normalizedTrustedRoot(trustedAssetRootPath)),
              let portLiteral = javaScriptStringLiteral(String(initialBackendPort)),
              let handlerNameLiteral = javaScriptStringLiteral(credentialMessageHandlerName),
              let headerLiteral = javaScriptStringLiteral(BackendAuthorization.tokenHeader),
              let acceptProtocolLiteral = javaScriptStringLiteral(BackendAuthorization.webSocketAcceptProtocol),
              let tokenProtocolPrefixLiteral = javaScriptStringLiteral(BackendAuthorization.webSocketTokenProtocolPrefix) else {
            return nil
        }
        return """
        (() => {
          const trustedRoot = \(rootLiteral);
          if (window.location.protocol !== 'file:') { return; }
          let pagePath = '';
          try { pagePath = decodeURIComponent(window.location.pathname); } catch (_) { return; }
          if (!pagePath.startsWith(trustedRoot)) { return; }
          if (window.__basilBackendAuthorizationInstalled) { return; }
          Object.defineProperty(window, '__basilBackendAuthorizationInstalled', { value: true });
          const handlerName = \(handlerNameLiteral);
          const tokenHeader = \(headerLiteral);
          const acceptProtocol = \(acceptProtocolLiteral);
          const tokenProtocolPrefix = \(tokenProtocolPrefixLiteral);
          let token = \(initialTokenLiteral);
          let backendPort = \(portLiteral);
          let pendingRefresh = null;
          const refreshCredentials = () => {
            const handlers = window.webkit && window.webkit.messageHandlers;
            const handler = handlers && handlers[handlerName];
            if (!handler) { return Promise.resolve(); }
            if (!pendingRefresh) {
              pendingRefresh = handler.postMessage(null)
                .then((reply) => {
                  if (reply && typeof reply.token === 'string') { token = reply.token; }
                  if (reply && typeof reply.port === 'string') { backendPort = reply.port; }
                })
                .catch(() => {})
                .finally(() => { pendingRefresh = null; });
            }
            return pendingRefresh;
          };
          const loopbackHosts = new Set(['127.0.0.1', 'localhost', '[::1]']);
          const parseLoopbackUrl = (value) => {
            let url;
            try { url = new URL(String(value), window.location.href); } catch (_) { return null; }
            if (url.protocol !== 'http:' && url.protocol !== 'ws:') { return null; }
            if (url.username || url.password) { return null; }
            return loopbackHosts.has(url.hostname) ? url : null;
          };
          const isCurrentBackend = (url) => token !== null && (url.port || '80') === backendPort;
          const nativeFetch = window.fetch.bind(window);
          window.fetch = function basilFetch(input, init) {
            const requestUrl = input instanceof Request ? input.url : input;
            const loopbackUrl = parseLoopbackUrl(requestUrl);
            if (!loopbackUrl) { return nativeFetch(input, init); }
            return refreshCredentials().then(() => {
              if (!isCurrentBackend(loopbackUrl)) { return nativeFetch(input, init); }
              const sourceHeaders = init && init.headers !== undefined
                ? init.headers
                : (input instanceof Request ? input.headers : undefined);
              const headers = new Headers(sourceHeaders);
              if (!headers.has(tokenHeader)) { headers.set(tokenHeader, token); }
              return nativeFetch(input, Object.assign({}, init, { headers }));
            });
          };
          const NativeWebSocket = window.WebSocket;
          function BasilWebSocket(url, protocols) {
            const loopbackUrl = parseLoopbackUrl(url);
            if (!loopbackUrl || !isCurrentBackend(loopbackUrl)) {
              if (loopbackUrl) { refreshCredentials(); }
              return protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
            }
            const offered = protocols === undefined
              ? []
              : (Array.isArray(protocols) ? protocols.slice() : [String(protocols)]);
            if (!offered.includes(acceptProtocol)) { offered.push(acceptProtocol); }
            offered.push(tokenProtocolPrefix + token);
            const socket = new NativeWebSocket(url, offered);
            socket.addEventListener('close', () => { refreshCredentials(); });
            return socket;
          }
          BasilWebSocket.prototype = NativeWebSocket.prototype;
          ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach((name) => {
            Object.defineProperty(BasilWebSocket, name, { value: NativeWebSocket[name] });
          });
          window.WebSocket = BasilWebSocket;
          refreshCredentials();
        })();
        """
    }

    nonisolated static func javaScriptStringLiteral(_ value: String) -> String? {
        guard let data = try? JSONEncoder().encode(value) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

/// Answers bundled pages' requests for the current web view token and backend port.
@MainActor
final class BackendCredentialMessageHandler: NSObject, WKScriptMessageHandlerWithReply {
    private let credentialStore: BackendCredentialStore
    private let backendPortProvider: @MainActor () -> Int
    private let trustedAssetRootPath: String

    init(
        credentialStore: BackendCredentialStore,
        backendPortProvider: @escaping @MainActor () -> Int,
        trustedAssetRootPath: String
    ) {
        self.credentialStore = credentialStore
        self.backendPortProvider = backendPortProvider
        self.trustedAssetRootPath = trustedAssetRootPath
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) async -> (Any?, String?) {
        Self.reply(
            isMainFrame: message.frameInfo.isMainFrame,
            frameURL: message.frameInfo.request.url,
            trustedAssetRootPath: trustedAssetRootPath,
            webviewToken: credentialStore.webviewToken,
            backendPort: backendPortProvider()
        )
    }

    nonisolated static func reply(
        isMainFrame: Bool,
        frameURL: URL?,
        trustedAssetRootPath: String,
        webviewToken: String?,
        backendPort: Int
    ) -> (Any?, String?) {
        let trustedRoot = BasilWebViewConfigurationFactory.normalizedTrustedRoot(trustedAssetRootPath)
        guard isMainFrame, let frameURL, frameURL.isFileURL,
              frameURL.standardizedFileURL.path.hasPrefix(trustedRoot) else {
            return (nil, "untrusted_frame")
        }
        guard let webviewToken, BackendCredentials.isValidToken(webviewToken) else {
            return (nil, "credentials_unavailable")
        }
        return (["token": webviewToken, "port": String(backendPort)], nil)
    }
}
