import AppKit

/// Resolves CoreAudio process identities into stable, user-friendly app names.
///
/// CoreAudio often reports browser meeting audio from helper processes. For
/// detection identity and UI labels, users should see the parent app (e.g.
/// "Google Chrome"), not a helper process name or reverse-DNS bundle ID.
enum AudioAppNameResolver {
    static func parentBundleID(from bundleID: String) -> String {
        var parts = bundleID.split(separator: ".").map(String.init)
        while let last = parts.last, last.lowercased().contains("helper") {
            parts.removeLast()
        }
        let joined = parts.joined(separator: ".")
        return joined.isEmpty ? bundleID : joined
    }

    static func displayName(forBundleID bundleID: String, bundleURL: URL?, pid: pid_t) -> String {
        if bundleID == "com.apple.avconferenced" {
            return "Apple Audio"
        }

        let appURL = resolvedAppURL(forBundleID: bundleID, bundleURL: bundleURL)

        if let appURL {
            if let bundle = Bundle(url: appURL) {
                if let displayName = bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String,
                   !displayName.isEmpty {
                    return displayName
                }
                if let bundleName = bundle.object(forInfoDictionaryKey: "CFBundleName") as? String,
                   !bundleName.isEmpty {
                    return bundleName
                }
            }

            let fileDisplayName = FileManager.default.displayName(atPath: appURL.path)
            if !fileDisplayName.isEmpty {
                return stripAppExtension(fileDisplayName)
            }
        }

        if let runningName = NSRunningApplication(processIdentifier: pid)?.localizedName {
            let stripped = stripHelperSuffix(from: runningName)
            if !stripped.isEmpty {
                return stripped
            }
        }

        return bundleID.components(separatedBy: ".").last.map { $0.capitalized } ?? "Unknown App"
    }

    static func displayName(forBundleID bundleID: String) -> String {
        displayName(forBundleID: bundleID, bundleURL: nil, pid: -1)
    }

    private static func resolvedAppURL(forBundleID bundleID: String, bundleURL: URL?) -> URL? {
        if let bundleURL, bundleURL.isApplicationBundle {
            return bundleURL
        }
        return NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID)
    }

    private static func stripHelperSuffix(from name: String) -> String {
        guard let range = name.range(of: " Helper") else { return name }
        return String(name[..<range.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func stripAppExtension(_ name: String) -> String {
        name.hasSuffix(".app") ? String(name.dropLast(4)) : name
    }
}

private extension URL {
    var isApplicationBundle: Bool {
        pathExtension.caseInsensitiveCompare("app") == .orderedSame
    }
}
