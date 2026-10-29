import Foundation

/// Decides which links clicked inside the setup window are handed to the user's default browser.
enum SetupAssistantLinkPolicy {
    /// Returns the URL to open externally, or nil when the link must not leave the app (a refused scheme, a local file, or no URL at all).
    static func externalURLToOpen(for url: URL?) -> URL? {
        guard let url, BridgeOpenPolicy.externalURLAction(for: url) == .open else {
            return nil
        }
        return url
    }
}
