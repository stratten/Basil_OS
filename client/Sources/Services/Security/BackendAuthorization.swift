import Foundation

/// Decides which requests are Basil backend requests and attaches the host credential to them.
enum BackendAuthorization {
    static let tokenHeader = "X-Basil-Token"
    static let webSocketTokenProtocolPrefix = "basil.token."
    static let webSocketAcceptProtocol = "basil.v1"

    private static let loopbackHosts: Set<String> = ["127.0.0.1", "localhost", "::1"]
    private static let backendSchemes: Set<String> = ["http", "ws"]

    static func isLoopbackBackendScheme(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(), backendSchemes.contains(scheme),
              let host = url.host?.lowercased() else {
            return false
        }
        return loopbackHosts.contains(host.trimmingCharacters(in: CharacterSet(charactersIn: "[]")))
    }

    static func isBackendURL(_ url: URL, backendPort: Int) -> Bool {
        guard isLoopbackBackendScheme(url), url.user == nil, url.password == nil else {
            return false
        }
        return (url.port ?? 80) == backendPort
    }

    static func isCurrentBackendURL(_ url: URL) -> Bool {
        isBackendURL(url, backendPort: APIClient.shared.currentPort)
    }

    static func authorizedRequest(for url: URL, credentialStore: BackendCredentialStore = .shared) -> URLRequest {
        authorizedRequest(URLRequest(url: url), credentialStore: credentialStore, backendPort: APIClient.shared.currentPort)
    }

    static func authorizedRequest(
        _ request: URLRequest,
        credentialStore: BackendCredentialStore,
        backendPort: Int
    ) -> URLRequest {
        guard let url = request.url, isBackendURL(url, backendPort: backendPort),
              let hostToken = credentialStore.hostToken else {
            return request
        }
        var authorized = request
        authorized.setValue(hostToken, forHTTPHeaderField: tokenHeader)
        return authorized
    }

    static func redirectRequest(
        _ request: URLRequest,
        credentialStore: BackendCredentialStore,
        backendPort: Int
    ) -> URLRequest {
        var stripped = request
        stripped.setValue(nil, forHTTPHeaderField: tokenHeader)
        return authorizedRequest(stripped, credentialStore: credentialStore, backendPort: backendPort)
    }
}
