import Foundation

/// Best-effort cleanup of a raw on-screen window title into a more specific
/// meeting label than the bare app name, e.g. turning a browser's
/// "Google Meet - Microsoft Edge" window title into "Google Meet" so an
/// ad-hoc call detected by audio activity alone (no calendar match) can show
/// "Google Meet" as the title and "Microsoft Edge" as the detection-source
/// badge, instead of "Microsoft Edge" in both places.
///
/// Deliberately conservative: only strips a trailing "- {appName}" suffix
/// (case-insensitively), since browsers vary in how much further profile or
/// tab-count metadata they append and a more aggressive split on every "-"
/// would risk truncating meeting titles that legitimately contain one (e.g.
/// "Product Sync - Engineering").
enum MeetingWindowTitleCleaner {
    static func cleanedTitle(rawWindowTitle: String?, appName: String) -> String? {
        guard let raw = rawWindowTitle else { return nil }
        let trimmedRaw = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedRaw.isEmpty else { return nil }

        var cleaned = trimmedRaw
        let suffix = "- \(appName)"
        if cleaned.lowercased().hasSuffix(suffix.lowercased()) {
            cleaned = String(cleaned.dropLast(suffix.count))
            cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        guard !cleaned.isEmpty, cleaned.caseInsensitiveCompare(appName) != .orderedSame else {
            return nil
        }
        return cleaned
    }
}
