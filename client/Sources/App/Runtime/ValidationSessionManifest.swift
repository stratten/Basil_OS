import Foundation

struct ValidationSessionManifest: Codable, Equatable {
    static let supportedSchemaVersion = 1

    enum Mode: String, Codable {
        case developerLocal
    }

    let schemaVersion: Int
    let sessionID: String
    let sessionRoot: URL
    let backendURL: URL
    let fixtureManifestURL: URL
    let probeURL: URL
    let credentialNamespace: String
    let createdAt: Date
    let mode: Mode

    func validated(sessionBaseURL: URL) throws -> ValidationSessionManifest {
        guard schemaVersion == Self.supportedSchemaVersion else {
            throw ValidationSessionManifestError.unsupportedSchemaVersion(schemaVersion)
        }
        guard !sessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ValidationSessionManifestError.emptyValue("sessionID")
        }
        guard sessionRoot.isFileURL, fixtureManifestURL.isFileURL, probeURL.isFileURL else {
            throw ValidationSessionManifestError.nonFileURL
        }

        let normalizedSessionBase = sessionBaseURL.resolvingSymlinksInPath().standardizedFileURL
        let normalizedSessionRoot = sessionRoot.resolvingSymlinksInPath().standardizedFileURL
        guard normalizedSessionRoot.isValidationDescendant(of: normalizedSessionBase), normalizedSessionRoot != normalizedSessionBase else {
            throw ValidationSessionManifestError.sessionRootOutsideValidationBase
        }
        guard fixtureManifestURL.resolvingSymlinksInPath().standardizedFileURL.isValidationDescendant(of: normalizedSessionRoot),
              probeURL.resolvingSymlinksInPath().standardizedFileURL.isValidationDescendant(of: normalizedSessionRoot) else {
            throw ValidationSessionManifestError.ownedPathOutsideSessionRoot
        }
        guard backendURL.scheme == "http",
              let host = backendURL.host?.lowercased(),
              host == "localhost" || host == "127.0.0.1",
              backendURL.port != nil,
              backendURL.user == nil,
              backendURL.password == nil,
              backendURL.path.isEmpty || backendURL.path == "/" else {
            throw ValidationSessionManifestError.invalidBackendURL
        }

        let expectedCredentialPrefix = "com.stratten.basil.validation.\(sessionID)."
        guard credentialNamespace.hasPrefix(expectedCredentialPrefix) else {
            throw ValidationSessionManifestError.invalidCredentialNamespace
        }
        return self
    }
}

private extension URL {
    func isValidationDescendant(of ancestor: URL) -> Bool {
        let ancestorComponents = ancestor.pathComponents
        let candidateComponents = pathComponents
        guard candidateComponents.count > ancestorComponents.count else {
            return false
        }
        return candidateComponents.prefix(ancestorComponents.count).elementsEqual(ancestorComponents)
    }
}

enum ValidationSessionManifestError: LocalizedError, Equatable {
    case unsupportedSchemaVersion(Int)
    case emptyValue(String)
    case nonFileURL
    case sessionRootOutsideValidationBase
    case ownedPathOutsideSessionRoot
    case invalidBackendURL
    case invalidCredentialNamespace

    var errorDescription: String? {
        switch self {
        case .unsupportedSchemaVersion(let version):
            return "Unsupported validation manifest schema version \(version)."
        case .emptyValue(let name):
            return "Validation manifest field \(name) must not be empty."
        case .nonFileURL:
            return "Validation manifest paths must be file URLs."
        case .sessionRootOutsideValidationBase:
            return "Validation session root is outside the owned sessions directory."
        case .ownedPathOutsideSessionRoot:
            return "Validation manifest contains a path outside its session root."
        case .invalidBackendURL:
            return "Validation backend URL must be an http loopback URL with a port."
        case .invalidCredentialNamespace:
            return "Validation credential namespace does not belong to this session."
        }
    }
}
