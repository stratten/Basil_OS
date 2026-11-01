import Foundation
import Combine

/// User-selectable date display style, owned by backend `GeneralSettings.date_display_style`.
enum DateDisplayStyle: String, CaseIterable, Identifiable {
    case relative
    case absolute

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .relative: return "Relative"
        case .absolute: return "Absolute"
        }
    }
}

/// Shared, observable holder for the current date display style.
///
/// It is an `ObservableObject` so SwiftUI history surfaces re-render live when the
/// preference changes, while still allowing synchronous reads from formatting helpers.
final class DateDisplayPreferenceStore: ObservableObject {
    static let shared = DateDisplayPreferenceStore()

    @Published var style: DateDisplayStyle = .relative

    private init() {}

    /// Update the style on the main thread (safe to call from any context).
    func update(_ newStyle: DateDisplayStyle) {
        if Thread.isMainThread {
            if style != newStyle { style = newStyle }
        } else {
            DispatchQueue.main.async {
                if self.style != newStyle { self.style = newStyle }
            }
        }
    }
}

/// Formatters shared across calls. Constructing an `ISO8601DateFormatter` or `DateFormatter` goes through ICU and costs far more than using one, and the meeting history bridge formats every visible row on the main thread each time it reconciles, so per-call construction visibly starves window animations. Each formatter is fully configured once and never mutated afterwards (a shared formatter must not have its `dateFormat` changed between calls), which makes `string(from:)` and `date(from:)` safe to call from any thread. Locale and time zone use the auto-updating variants so a change made while the app is running still takes effect, exactly as it did when a fresh formatter was built per call.
private enum SharedDateFormatters {
    static let internetDateTimeWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static let internetDateTime: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    static let sidebar: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = .autoupdatingCurrent
        formatter.timeZone = .autoupdatingCurrent
        formatter.dateFormat = "yyyy-MM-dd h:mm a"
        formatter.amSymbol = "am"
        formatter.pmSymbol = "pm"
        return formatter
    }()

    static let shortTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = .autoupdatingCurrent
        formatter.timeStyle = .short
        return formatter
    }()

    static let weekdayAndTime = localizedFormatter("EEEE, h:mm a")
    static let monthDayAndTime = localizedFormatter("MMM d, h:mm a")

    static let localMicroseconds = posixLocalFormatter("yyyy-MM-dd'T'HH:mm:ss.SSSSSS")
    static let localMilliseconds = posixLocalFormatter("yyyy-MM-dd'T'HH:mm:ss.SSS")
    static let localSeconds = posixLocalFormatter("yyyy-MM-dd'T'HH:mm:ss")
    static let localDateOnly = posixLocalFormatter("yyyy-MM-dd")

    static let utcMilliseconds = posixUTCFormatter("yyyy-MM-dd HH:mm:ss.SSS")
    static let utcSeconds = posixUTCFormatter("yyyy-MM-dd HH:mm:ss")

    private static func localizedFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = .autoupdatingCurrent
        formatter.dateFormat = format
        return formatter
    }

    /// Parses wall-clock text in the user's local timezone (matches the backend, which writes `datetime.now().isoformat()` as local time).
    private static func posixLocalFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .autoupdatingCurrent
        formatter.dateFormat = format
        return formatter
    }

    private static func posixUTCFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = format
        return formatter
    }
}

enum DateFormattingUtils {
    /// Standard absolute date format: yyyy-MM-dd h:mm a
    /// Uses the user's current timezone
    static func sidebarFormat(_ date: Date) -> String {
        return SharedDateFormatters.sidebar.string(from: date)
    }

    /// Relative date format (e.g., "Today, 10:45 AM", "Yesterday, 10:45 AM",
    /// "Monday, 10:45 AM", "Jun 28, 10:45 AM"). Uses the user's current timezone.
    static func relativeFormat(_ date: Date) -> String {
        let calendar = Calendar.current
        let now = Date()

        if calendar.isDateInToday(date) {
            return "Today, \(SharedDateFormatters.shortTime.string(from: date))"
        } else if calendar.isDateInYesterday(date) {
            return "Yesterday, \(SharedDateFormatters.shortTime.string(from: date))"
        } else if calendar.isDate(date, equalTo: now, toGranularity: .weekOfYear) {
            return SharedDateFormatters.weekdayAndTime.string(from: date)
        } else {
            return SharedDateFormatters.monthDayAndTime.string(from: date)
        }
    }

    /// Parses only timestamps that carry an explicit timezone (for example `Z` or `+00:00`), with or without fractional seconds. Returns nil for timezone-less text; `parseISO8601` adds the fallback formats on top of this.
    static func parseInternetDateTime(_ timestamp: String) -> Date? {
        if let date = SharedDateFormatters.internetDateTimeWithFractionalSeconds.date(from: timestamp) { return date }
        return SharedDateFormatters.internetDateTime.date(from: timestamp)
    }

    /// Parse ISO8601 timestamp (with various fallback options)
    static func parseISO8601(_ timestamp: String) -> Date? {
        // First, try ISO8601DateFormatter for timestamps WITH explicit timezone (Z or +00:00)
        // These are genuinely UTC timestamps that need timezone conversion
        if let date = parseInternetDateTime(timestamp) { return date }
        
        // For timestamps WITHOUT timezone info (e.g., "2026-01-23T10:17:41.213599")
        // Backend uses datetime.now().isoformat() which is LOCAL time, not UTC
        // Do NOT append "Z" - that would incorrectly interpret local time as UTC
        // Parsed as local time (matches backend behavior)
        
        // Try with microseconds
        if let date = SharedDateFormatters.localMicroseconds.date(from: timestamp) { return date }
        
        // Try with milliseconds
        if let date = SharedDateFormatters.localMilliseconds.date(from: timestamp) { return date }
        
        // Try without fractional seconds
        if let date = SharedDateFormatters.localSeconds.date(from: timestamp) { return date }
        
        // Try date only (no time component, parsed as local midnight)
        if let date = SharedDateFormatters.localDateOnly.date(from: timestamp) { return date }

        // SQLite CURRENT_TIMESTAMP shape: "2026-06-29 14:45:00" (space-separated, tz-less UTC).
        // These are genuinely UTC and MUST be interpreted as such, unlike the 'T' branches above.
        if let date = SharedDateFormatters.utcMilliseconds.date(from: timestamp) { return date }

        if let date = SharedDateFormatters.utcSeconds.date(from: timestamp) { return date }

        return nil
    }
    
    /// Combined: parse timestamp and format using the supplied style.
    static func formatTimestamp(_ timestamp: String, style: DateDisplayStyle) -> String {
        guard let date = parseISO8601(timestamp) else { return timestamp }
        switch style {
        case .relative: return relativeFormat(date)
        case .absolute: return sidebarFormat(date)
        }
    }

    /// Combined: parse timestamp and format using the current shared preference.
    static func formatTimestamp(_ timestamp: String) -> String {
        return formatTimestamp(timestamp, style: DateDisplayPreferenceStore.shared.style)
    }
}
