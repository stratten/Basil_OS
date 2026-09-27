import Foundation
import EventKit

/// macOS EventKit implementation of ``MeetingCalendarProviding``.
///
/// EventKit transparently covers Google/M365/iCloud calendars already synced to
/// macOS, so this single provider works regardless of the user's calendar
/// backend. Access is lazy and non-intrusive: ``currentEvent()`` only reads when
/// full access has already been granted and never triggers a permission prompt
/// during a background probe. The prompt is raised explicitly via
/// ``requestAccess()`` when the user opts into calendar features in Settings.
@available(macOS 14.0, *)
final class EventKitCalendarProvider: MeetingCalendarProviding {

    static let shared = EventKitCalendarProvider()

    private let store = EKEventStore()

    /// Explicitly request calendar access (used when the user enables a calendar
    /// feature in Settings). Returns whether access is granted.
    @discardableResult
    func requestAccess() async -> Bool {
        do {
            return try await store.requestFullAccessToEvents()
        } catch {
            #if DEBUG
            DevLogger.shared.error("EventKit access request failed: \(error.localizedDescription)", context: "MeetingDetection")
            #endif
            return false
        }
    }

    func currentEvent() async -> MeetingCalendarEvent? {
        // Never prompt during a probe; only read when already authorized.
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else {
            return nil
        }

        let now = Date()
        return await joinableEvents(
            from: now.addingTimeInterval(-1),
            to: now.addingTimeInterval(1)
        ).first
    }

    func joinableEvents(from startDate: Date, to endDate: Date) async -> [MeetingCalendarEvent] {
        // Never prompt during a probe; only read when already authorized.
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else {
            return []
        }

        let predicate = store.predicateForEvents(
            withStart: startDate,
            end: endDate,
            calendars: nil
        )

        let events = store.events(matching: predicate).filter { event in
            !event.isAllDay && event.startDate <= endDate && event.endDate >= startDate
        }
        return events.compactMap { event -> MeetingCalendarEvent? in
            let callInfo = meetingCallInfo(for: event)
            guard callInfo.hasCallInfo else { return nil }

            let attendees = (event.attendees ?? []).compactMap { $0.name }
            return MeetingCalendarEvent(
                eventIdentifier: event.calendarItemExternalIdentifier.isEmpty ? event.eventIdentifier : event.calendarItemExternalIdentifier,
                title: event.title ?? "Meeting",
                calendarName: event.calendar.title,
                attendees: attendees,
                startTimestamp: event.startDate?.timeIntervalSince1970,
                endTimestamp: event.endDate?.timeIntervalSince1970,
                joinURL: callInfo.joinURL?.absoluteString,
                hasCallInfo: callInfo.hasCallInfo
            )
        }
    }

    private func meetingCallInfo(for event: EKEvent) -> (joinURL: URL?, hasCallInfo: Bool) {
        let sourceStrings = [
            event.url?.absoluteString,
            event.location,
            event.notes,
            event.structuredLocation?.title
        ].compactMap { $0 }

        for source in sourceStrings {
            if let directURL = URL(string: source), isMeetingURL(directURL) {
                return (directURL, true)
            }
            if let detectedURL = firstMeetingURL(in: source) {
                return (detectedURL, true)
            }
        }

        return (nil, false)
    }

    private func firstMeetingURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else {
            return nil
        }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        let matches = detector.matches(in: text, options: [], range: range)
        return matches.compactMap { $0.url }.first(where: isMeetingURL)
    }

    private func isMeetingURL(_ url: URL) -> Bool {
        let meetingSchemes = ["zoommtg", "zoomus", "msteams", "facetime"]
        if let scheme = url.scheme?.lowercased(), meetingSchemes.contains(scheme) {
            return true
        }

        guard let host = url.host?.lowercased() else { return false }
        let meetingHosts = [
            "zoom.us",
            "meet.google.com",
            "teams.microsoft.com",
            "teams.live.com",
            "webex.com",
            "bluejeans.com",
            "whereby.com",
            "gotomeeting.com",
            "chime.aws",
            "facetime.apple.com",
            "slack.com"
        ]
        return meetingHosts.contains { host == $0 || host.hasSuffix(".\($0)") }
    }
}

/// Availability-erased entry point for requesting calendar access from code that
/// isn't gated to macOS 14 (e.g. the settings view model).
enum MeetingDetectionCalendarAccess {
    @discardableResult
    static func requestIfNeeded() async -> Bool {
        if #available(macOS 14.0, *) {
            return await EventKitCalendarProvider.shared.requestAccess()
        }
        return false
    }
}
