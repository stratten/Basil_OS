import Darwin
import Foundation

struct BackendCredentials: Equatable, Sendable {
    let hostToken: String
    let webviewToken: String

    static let fileVersion = 1
    private static let tokenByteCount = 32
    private static let hexDigits = Set("0123456789abcdef")

    static func isValidToken(_ value: String) -> Bool {
        value.count == tokenByteCount * 2 && value.allSatisfy { hexDigits.contains($0) }
    }

    static func parse(_ data: Data) -> BackendCredentials? {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = payload["version"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(),
              version.intValue == fileVersion,
              version.doubleValue == Double(fileVersion),
              let hostToken = payload["host_token"] as? String,
              let webviewToken = payload["webview_token"] as? String,
              isValidToken(hostToken),
              isValidToken(webviewToken),
              hostToken != webviewToken else {
            return nil
        }
        return BackendCredentials(hostToken: hostToken, webviewToken: webviewToken)
    }
}

/// Reads and caches the per-launch credentials that the Python backend writes; the client never generates or rotates them.
final class BackendCredentialStore: @unchecked Sendable {
    static let shared = BackendCredentialStore(fileURL: BackendCredentialStore.defaultFileURL)

    static var defaultFileURL: URL {
        BasilRuntimeProfile.localHomeURL
            .appendingPathComponent(".basil", isDirectory: true)
            .appendingPathComponent("runtime", isDirectory: true)
            .appendingPathComponent("backend_credentials.json", isDirectory: false)
    }

    let fileURL: URL
    private let lock = NSLock()
    private var cachedSignature: FileSignature?
    private var cachedCredentials: BackendCredentials?

    init(fileURL: URL) {
        self.fileURL = fileURL
    }

    func current() -> BackendCredentials? {
        lock.lock()
        defer { lock.unlock() }
        return readIfChanged()
    }

    var hostToken: String? { current()?.hostToken }

    var webviewToken: String? { current()?.webviewToken }

    private func readIfChanged() -> BackendCredentials? {
        guard let signature = FileSignature(path: fileURL.path) else {
            cachedSignature = nil
            cachedCredentials = nil
            return nil
        }
        if signature == cachedSignature, let cachedCredentials {
            return cachedCredentials
        }
        cachedSignature = nil
        cachedCredentials = nil
        guard signature.ownerID == getuid(), signature.permissions & 0o077 == 0,
              let data = FileManager.default.contents(atPath: fileURL.path),
              let credentials = BackendCredentials.parse(data) else {
            return nil
        }
        cachedSignature = signature
        cachedCredentials = credentials
        return credentials
    }
}

struct FileSignature: Equatable {
    let inode: UInt64
    let modificationSeconds: Int
    let modificationNanoseconds: Int
    let size: Int64
    let ownerID: uid_t
    let permissions: mode_t

    init?(path: String) {
        var info = stat()
        guard stat(path, &info) == 0 else { return nil }
        inode = UInt64(info.st_ino)
        modificationSeconds = info.st_mtimespec.tv_sec
        modificationNanoseconds = info.st_mtimespec.tv_nsec
        size = Int64(info.st_size)
        ownerID = info.st_uid
        permissions = info.st_mode & 0o7777
    }
}
