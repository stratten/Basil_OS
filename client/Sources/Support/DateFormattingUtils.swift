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

enum DateFormattingUtils {
    /// Standard absolute date format: yyyy-MM-dd h:mm a
    /// Uses the user's current timezone
    static func sidebarFormat(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd h:mm a"
        formatter.amSymbol = "am"
        formatter.pmSymbol = "pm"
        formatter.timeZone = .current  // Explicit: use user's local timezone
        return formatter.string(from: date)
    }

    /// Relative date format (e.g., "Today, 10:45 AM", "Yesterday, 10:45 AM",
    /// "Monday, 10:45 AM", "Jun 28, 10:45 AM"). Uses the user's current timezone.
    static func relativeFormat(_ date: Date) -> String {
        let calendar = Calendar.current
        let now = Date()

        if calendar.isDateInToday(date) {
            let formatter = DateFormatter()
            formatter.timeStyle = .short
            return "Today, \(formatter.string(from: date))"
        } else if calendar.isDateInYesterday(date) {
            let formatter = DateFormatter()
            formatter.timeStyle = .short
            return "Yesterday, \(formatter.string(from: date))"
        } else if calendar.isDate(date, equalTo: now, toGranularity: .weekOfYear) {
            let formatter = DateFormatter()
            formatter.dateFormat = "EEEE, h:mm a"
            return formatter.string(from: date)
        } else {
            let formatter = DateFormatter()
            formatter.dateFormat = "MMM d, h:mm a"
            return formatter.string(from: date)
        }
    }

    /// Parse ISO8601 timestamp (with various fallback options)
    static func parseISO8601(_ timestamp: String) -> Date? {
        // First, try ISO8601DateFormatter for timestamps WITH explicit timezone (Z or +00:00)
        // These are genuinely UTC timestamps that need timezone conversion
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = isoFormatter.date(from: timestamp) { return date }
        
        isoFormatter.formatOptions = [.withInternetDateTime]
        if let date = isoFormatter.date(from: timestamp) { return date }
        
        // For timestamps WITHOUT timezone info (e.g., "2026-01-23T10:17:41.213599")
        // Backend uses datetime.now().isoformat() which is LOCAL time, not UTC
        // Do NOT append "Z" - that would incorrectly interpret local time as UTC
        let dateFormatter = DateFormatter()
        dateFormatter.locale = Locale(identifier: "en_US_POSIX")
        dateFormatter.timeZone = .current  // Parse as local time (matches backend behavior)
        
        // Try with microseconds
        dateFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        if let date = dateFormatter.date(from: timestamp) { return date }
        
        // Try with milliseconds
        dateFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSS"
        if let date = dateFormatter.date(from: timestamp) { return date }
        
        // Try without fractional seconds
        dateFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        if let date = dateFormatter.date(from: timestamp) { return date }
        
        // Try date only (no time component, treat as midnight UTC)
        dateFormatter.dateFormat = "yyyy-MM-dd"
        if let date = dateFormatter.date(from: timestamp) { return date }

        // SQLite CURRENT_TIMESTAMP shape: "2026-06-29 14:45:00" (space-separated, tz-less UTC).
        // These are genuinely UTC and MUST be interpreted as such, unlike the 'T' branches above.
        let utcFormatter = DateFormatter()
        utcFormatter.locale = Locale(identifier: "en_US_POSIX")
        utcFormatter.timeZone = TimeZone(identifier: "UTC")

        utcFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        if let date = utcFormatter.date(from: timestamp) { return date }

        utcFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        if let date = utcFormatter.date(from: timestamp) { return date }

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
