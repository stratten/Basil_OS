import Foundation

// MARK: - Probe payload types
//
// These are the platform-agnostic results the client reports back to the
// backend meeting-detection loop. Detection policy (edges, cooldown, calendar
// gating, prompt vs auto-start) lives in Python; the client only answers the
// mechanical question "which non-excluded processes are using both input and
// output audio right now, and is a calendar event currently active?".

/// A process that currently looks like a meeting (input + output active).
struct DetectedMeetingApp: Codable, Equatable {
    let name: String
    let bundleID: String
    let pid: Int32
    /// The active app's on-screen window title at probe time, already run
    /// through `MeetingWindowTitleCleaner` to strip a trailing "- {name}"
    /// suffix. `nil` when no matching on-screen window was found or the
    /// cleaned result would just repeat `name`.
    let windowTitle: String?

    enum CodingKeys: String, CodingKey {
        case name
        case bundleID = "bundle_id"
        case pid
        case windowTitle = "window_title"
    }
}

/// The calendar event (if any) active at probe time, used to enrich/gate a
/// detected meeting. Timestamps are Unix seconds.
struct MeetingCalendarEvent: Codable, Equatable {
    let eventIdentifier: String
    let title: String
    let calendarName: String?
    let attendees: [String]
    let startTimestamp: Double?
    let endTimestamp: Double?
    let joinURL: String?
    let hasCallInfo: Bool

    enum CodingKeys: String, CodingKey {
        case eventIdentifier = "event_identifier"
        case title
        case calendarName = "calendar_name"
        case attendees
        case startTimestamp = "start_timestamp"
        case endTimestamp = "end_timestamp"
        case joinURL = "join_url"
        case hasCallInfo = "has_call_info"
    }
}

/// Aggregate result of a single probe.
struct MeetingProbeResult: Equatable {
    var activeMeetingApps: [DetectedMeetingApp]
    var currentCalendarEvent: MeetingCalendarEvent?

    static let empty = MeetingProbeResult(activeMeetingApps: [], currentCalendarEvent: nil)
}

// MARK: - Abstractions (OS-swappable)

/// Stateless audio-activity probe. A future OS port provides its own
/// implementation; nothing else in the pipeline changes.
protocol MeetingActivityProbing {
    /// Report which non-excluded processes are currently using input + output
    /// audio, plus the current calendar event if a provider is available.
    func probe(excludedBundleIDs: [String]) async -> MeetingProbeResult
}

/// Calendar access abstraction. macOS uses EventKit; other platforms can supply
/// their own. Returns the event considered "current" (covering now).
protocol MeetingCalendarProviding {
    func currentEvent() async -> MeetingCalendarEvent?
    func joinableEvents(from startDate: Date, to endDate: Date) async -> [MeetingCalendarEvent]
}
