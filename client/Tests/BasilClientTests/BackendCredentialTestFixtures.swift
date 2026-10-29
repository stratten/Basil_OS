import Darwin
import Foundation

enum BackendCredentialTestFixtures {
    struct RenameFailed: Error {
        let errno: Int32
    }

    static func payload(
        host: String = String(repeating: "a", count: 64),
        webview: String = String(repeating: "b", count: 64)
    ) -> [String: Any] {
        ["version": 1, "host_token": host, "webview_token": webview, "created_at": "2026-01-01T00:00:00+00:00"]
    }

    static func write(_ payload: [String: Any], to fileURL: URL, permissions: Int = 0o600) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        try data.write(to: fileURL)
        try FileManager.default.setAttributes([.posixPermissions: permissions], ofItemAtPath: fileURL.path)
    }

    static func atomicallyReplace(_ fileURL: URL, with payload: [String: Any]) throws {
        let replacementURL = fileURL.deletingLastPathComponent()
            .appendingPathComponent(".replacement-\(UUID().uuidString).json", isDirectory: false)
        try write(payload, to: replacementURL)
        guard rename(replacementURL.path, fileURL.path) == 0 else {
            throw RenameFailed(errno: errno)
        }
    }
}
