import Foundation

/// Package 5A.1: canonicalizes a native directory-picker selection into the resolved
/// path Basil hands back to the web bridge. This only proves the native half of the
/// eventual provider workspace-grant contract; it does not enforce that contract's
/// stricter "no symlink component" rule, which remains owned exclusively by
/// `ProviderLaunchValidationService` on the backend at a later grant/launch step.
enum WorkspaceDirectoryCanonicalizer {
    enum Failure: Equatable, Error {
        case notAbsolute
        case doesNotExist
        case notADirectory
        case notAccessible

        var userMessage: String {
            switch self {
            case .notAbsolute:
                return "The selected location is not a valid absolute path."
            case .doesNotExist:
                return "The selected folder no longer exists."
            case .notADirectory:
                return "The selected location is not a folder."
            case .notAccessible:
                return "The selected folder is not accessible."
            }
        }
    }

    /// Returns the resolved, symlink-followed absolute path for `url`, or the specific
    /// reason it cannot be used as a workspace directory.
    static func canonicalize(_ url: URL) -> Result<String, Failure> {
        let standardized = url.standardizedFileURL
        guard standardized.path.hasPrefix("/") else {
            return .failure(.notAbsolute)
        }

        let resolvedPath = standardized.resolvingSymlinksInPath().path
        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: resolvedPath, isDirectory: &isDirectory)
        guard exists else {
            return .failure(.doesNotExist)
        }
        guard isDirectory.boolValue else {
            return .failure(.notADirectory)
        }
        guard FileManager.default.isReadableFile(atPath: resolvedPath),
              FileManager.default.isExecutableFile(atPath: resolvedPath) else {
            return .failure(.notAccessible)
        }
        return .success(resolvedPath)
    }
}
