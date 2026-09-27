import Foundation

/// Client responder for the backend mechanical meeting-detection loop.
///
/// The backend sends `event_type:"audio_activity_probe"` over the WS; we run the
/// platform probe (CoreAudio `IsRunningInput` + `IsRunningOutput` for
/// non-excluded bundle IDs, plus an optional calendar read) and POST the result back to
/// `/audio-activity/probe-response`, mirroring the window-capture bridge.
extension WebSocketService {

    /// Shared probe instance. Calendar enrichment is injected lazily; the
    /// provider never prompts during background probes.
    @MainActor
    private static var meetingActivityProbe: MeetingActivityProbing = {
        if #available(macOS 14.0, *) {
            return CoreAudioMeetingActivityProbe(calendarProvider: MeetingDetectionCalendarProviderFactory.makeIfAvailable())
        } else {
            return NullMeetingActivityProbe()
        }
    }()

    @MainActor
    private static var meetingCalendarProvider: MeetingCalendarProviding? = {
        if #available(macOS 14.0, *) {
            return MeetingDetectionCalendarProviderFactory.makeIfAvailable()
        }
        return nil
    }()

    @MainActor
    func handleAudioActivityProbe(_ json: [String: Any]) {
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("Audio activity probe missing request_id", context: "websocket")
            #endif
            return
        }

        let excludedBundleIDs = json["excluded_bundle_ids"] as? [String] ?? []

        Task { @MainActor in
            let result = await Self.meetingActivityProbe.probe(excludedBundleIDs: excludedBundleIDs)
            await Self.sendAudioProbeResponse(requestId: requestId, result: result)
        }
    }

    @MainActor
    func handleMeetingCalendarProbe(_ json: [String: Any]) {
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("Meeting calendar probe missing request_id", context: "websocket")
            #endif
            return
        }

        let formatter = ISO8601DateFormatter()
        guard let windowStartString = json["window_start"] as? String,
              let windowEndString = json["window_end"] as? String,
              let windowStart = formatter.date(from: windowStartString),
              let windowEnd = formatter.date(from: windowEndString) else {
            Task { @MainActor in
                await Self.sendCalendarProbeResponse(requestId: requestId, events: [], success: false)
            }
            return
        }

        Task { @MainActor in
            let events = await Self.meetingCalendarProvider?.joinableEvents(from: windowStart, to: windowEnd) ?? []
            await Self.sendCalendarProbeResponse(requestId: requestId, events: events, success: true)
        }
    }

    @MainActor
    private static func sendAudioProbeResponse(requestId: String, result: MeetingProbeResult) async {
        let apiBase = APIClient.shared.baseURL
        guard let url = URL(string: "\(apiBase)/audio-activity/probe-response") else {
            #if DEBUG
            DevLogger.shared.error("Invalid audio probe response URL", context: "websocket")
            #endif
            return
        }

        var responseData: [String: Any] = [
            "request_id": requestId,
            "success": true,
            "timestamp": Int(Date().timeIntervalSince1970 * 1000),
            "active_meeting_apps": result.activeMeetingApps.map { app in
                [
                    "name": app.name,
                    "bundle_id": app.bundleID,
                    "pid": Int(app.pid),
                    "window_title": app.windowTitle ?? NSNull()
                ] as [String: Any]
            }
        ]

        if let event = result.currentCalendarEvent {
            responseData["current_calendar_event"] = dictionary(for: event)
        } else {
            responseData["current_calendar_event"] = NSNull()
        }

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 10.0
            request.httpBody = try JSONSerialization.data(withJSONObject: responseData)

            let (_, response) = try await URLSession.shared.data(for: request)
            #if DEBUG
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
                DevLogger.shared.error("Audio probe response failed with status: \(httpResponse.statusCode)", context: "websocket")
            } else {
                DevLogger.shared.info("Audio probe response sent (\(result.activeMeetingApps.count) active apps)", context: "websocket")
            }
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to send audio probe response: \(error)", context: "websocket")
            #endif
        }
    }

    @MainActor
    private static func sendCalendarProbeResponse(requestId: String, events: [MeetingCalendarEvent], success: Bool) async {
        let apiBase = APIClient.shared.baseURL
        guard let url = URL(string: "\(apiBase)/meeting-detection/calendar-probe-response") else {
            #if DEBUG
            DevLogger.shared.error("Invalid calendar probe response URL", context: "websocket")
            #endif
            return
        }

        let responseData: [String: Any] = [
            "request_id": requestId,
            "success": success,
            "timestamp": Int(Date().timeIntervalSince1970 * 1000),
            "joinable_events": events.map { dictionary(for: $0) }
        ]

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 10.0
            request.httpBody = try JSONSerialization.data(withJSONObject: responseData)

            let (_, response) = try await URLSession.shared.data(for: request)
            #if DEBUG
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
                DevLogger.shared.error("Calendar probe response failed with status: \(httpResponse.statusCode)", context: "websocket")
            } else {
                DevLogger.shared.info("Calendar probe response sent (\(events.count) joinable events)", context: "websocket")
            }
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to send calendar probe response: \(error)", context: "websocket")
            #endif
        }
    }

    private static func dictionary(for event: MeetingCalendarEvent) -> [String: Any] {
        var eventDict: [String: Any] = [
            "event_identifier": event.eventIdentifier,
            "title": event.title,
            "attendees": event.attendees,
            "has_call_info": event.hasCallInfo
        ]
        if let calendarName = event.calendarName, !calendarName.isEmpty {
            eventDict["calendar_name"] = calendarName
        }
        if let start = event.startTimestamp { eventDict["start_timestamp"] = start }
        if let end = event.endTimestamp { eventDict["end_timestamp"] = end }
        if let joinURL = event.joinURL { eventDict["join_url"] = joinURL }
        return eventDict
    }
}

/// Fallback probe for unsupported OS versions: reports no activity.
private struct NullMeetingActivityProbe: MeetingActivityProbing {
    func probe(excludedBundleIDs: [String]) async -> MeetingProbeResult { .empty }
}
