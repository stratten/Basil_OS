import Foundation

enum BasilRuntimeProfile: Equatable {
    case normal
    case validation(ValidationSessionManifest)

    enum BootstrapResult: Equatable {
        case success(BasilRuntimeProfile)
        case failure(String)
    }

    private(set) static var current: BasilRuntimeProfile = .normal

    static var isValidation: Bool {
        if case .validation = current {
            return true
        }
        return false
    }

    static var validationManifest: ValidationSessionManifest? {
        guard case .validation(let manifest) = current else {
            return nil
        }
        return manifest
    }

    /// A validation session launched as a first-time install of the real app.
    static var isFreshInstall: Bool {
        validationManifest?.freshInstall == true
    }

    /// True for a fixture validation session, which keeps off the behavior that could collide with a normal Basil running on this Mac: global hotkeys, key monitors, the setup resume toast, and meeting and activity startup. A fresh-install session turns them back on, so only one Basil may run, unless it was launched to coexist with a normal Basil, which keeps them off.
    static var suppressesAmbientBehavior: Bool {
        isValidation && (!isFreshInstall || validationManifest?.suppressAmbientBehavior == true)
    }

    /// True when the first-run permission gate is skipped. Only a fixture session skips it: a fresh-install session always shows it, even one that keeps ambient behavior off to coexist with a normal Basil.
    static var skipsFirstRunPermissionGate: Bool {
        isValidation && !isFreshInstall
    }

    static var backendURL: URL? {
        validationManifest?.backendURL
    }

    static var sessionRootURL: URL? {
        validationManifest?.sessionRoot
    }

    static var localHomeURL: URL {
        guard let sessionRootURL else {
            return FileManager.default.homeDirectoryForCurrentUser
        }
        return sessionRootURL.appendingPathComponent("home", isDirectory: true)
    }

    static var userDefaults: UserDefaults {
        guard case .validation(let manifest) = current else {
            return .standard
        }
        return UserDefaults(suiteName: manifest.credentialNamespace) ?? .standard
    }

    static func credentialKey(_ normalKey: String) -> String {
        guard case .validation(let manifest) = current else {
            return normalKey
        }
        return "\(manifest.credentialNamespace)\(normalKey)"
    }

    static func bootstrap(arguments: [String]) -> BootstrapResult {
        bootstrap(
            arguments: arguments,
            sessionBaseURL: defaultSessionBaseURL
        )
    }

    static func bootstrap(arguments: [String], sessionBaseURL: URL) -> BootstrapResult {
        let indices = arguments.indices.filter { arguments[$0] == "--validation-session" }
        guard !indices.isEmpty else {
            return .success(.normal)
        }
        guard indices.count == 1 else {
            return .failure("Validation launch rejected: --validation-session may be supplied only once.")
        }
        guard let flagIndex = indices.first else {
            return .failure("Validation launch rejected: missing --validation-session value.")
        }
        let valueIndex = arguments.index(after: flagIndex)
        guard valueIndex < arguments.endIndex else {
            return .failure("Validation launch rejected: missing --validation-session value.")
        }

        let manifestPath = arguments[valueIndex]
        guard manifestPath.hasPrefix("/") else {
            return .failure("Validation launch rejected: manifest path must be absolute.")
        }
        let manifestURL = URL(fileURLWithPath: manifestPath).standardizedFileURL
        do {
            let data = try Data(contentsOf: manifestURL)
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let manifest = try decoder.decode(ValidationSessionManifest.self, from: data)
            return .success(.validation(try manifest.validated(sessionBaseURL: sessionBaseURL)))
        } catch let error as ValidationSessionManifestError {
            return .failure("Validation launch rejected: \(error.localizedDescription)")
        } catch {
            return .failure("Validation launch rejected: could not load manifest (\(error.localizedDescription)).")
        }
    }

    static func install(_ profile: BasilRuntimeProfile) {
        current = profile
    }

    static func resetForTesting() {
        current = .normal
    }

    private static var defaultSessionBaseURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/BasilValidation/sessions", isDirectory: true)
            .standardizedFileURL
    }
}
