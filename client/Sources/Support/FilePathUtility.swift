import Foundation

/// Utility for converting between different path formats
enum FilePathUtility {
    /// Resolves artifact paths received from the web bridge without applying UI fallbacks.
    /// - Returns: An absolute POSIX path, or `nil` when the bridge value is not an absolute file location.
    static func resolveBridgeArtifactPath(_ path: String) -> String? {
        guard !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }

        if path.hasPrefix("/") {
            return path
        }

        if let url = URL(string: path), url.scheme?.caseInsensitiveCompare("file") == .orderedSame {
            guard url.isFileURL, url.path.hasPrefix("/") else {
                return nil
            }
            return url.path
        }

        guard path.contains(":"), !path.hasPrefix(":") else {
            return nil
        }

        return convertToUnixPath(path)
    }

    /// Converts various path formats to Unix/POSIX paths
    /// - Handles AppleScript-style paths (Macintosh HD:Users:...)
    /// - Expands tilde (~) paths
    /// - Treats bare filenames as Desktop-relative
    static func convertToUnixPath(_ path: String) -> String {
        // Handle AppleScript-style paths (Macintosh HD:Users:...) to Unix paths (/Users/...)
        if path.contains(":") {
            let components = path.components(separatedBy: ":")
            if components.count > 1 {
                // Skip "Macintosh HD" and join with "/"
                let unixComponents = Array(components.dropFirst())
                return resolveCurrentUserFallback("/" + unixComponents.joined(separator: "/"))
            }
        }
        // Expand tilde if present and ensure absolute POSIX path
        let expanded = (path as NSString).expandingTildeInPath
        if expanded.hasPrefix("/") {
            return resolveCurrentUserFallback(expanded)
        }
        // Treat bare filename as Desktop fallback
        return resolveCurrentUserFallback("/Users/\(NSUserName())/Desktop/\(expanded)")
    }

    private static func resolveCurrentUserFallback(_ path: String) -> String {
        guard !FileManager.default.fileExists(atPath: path) else { return path }

        let components = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard components.count > 3,
              components[0].isEmpty,
              components[1] == "Users",
              components[2] != NSUserName() else {
            return path
        }

        let relativeTail = components.dropFirst(3).joined(separator: "/")
        let currentUserPath = "/Users/\(NSUserName())/\(relativeTail)"
        return FileManager.default.fileExists(atPath: currentUserPath) ? currentUserPath : path
    }
}
