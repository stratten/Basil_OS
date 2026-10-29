import Foundation

/// Factory that vends the platform calendar provider used to enrich/gate
/// detected meetings.
///
/// Returns `nil` until calendar enrichment is wired (EventKit on macOS), which
/// keeps the probe audio-only by default and avoids prompting for calendar
/// access before the user opts in.
enum MeetingDetectionCalendarProviderFactory {
    static func makeIfAvailable() -> MeetingCalendarProviding? {
        if #available(macOS 14.0, *) {
            // The provider reads calendar data only when access has already been
            // granted; it never prompts during a probe, so it's safe to inject
            // unconditionally. Access is requested explicitly when the user opts
            // into calendar features in Settings.
            return EventKitCalendarProvider.shared
        }
        return nil
    }
}
