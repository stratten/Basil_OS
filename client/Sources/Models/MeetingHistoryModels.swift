import Foundation

// MARK: - Meeting List Item

/// Represents a meeting in the history list
struct MeetingListItem: Identifiable, Codable {
    let id: String
    let name: String
    let purpose: String?
    let participants: [String]
    let startTime: String
    let endTime: String?
    let durationSeconds: Double?
    let audioPath: String?
    let transcriptPath: String?
    let isPostProcessed: Bool
    let analysisSummary: AnalysisSummary?
    // Shared id linking the mic + system-audio recordings of one meeting
    let sessionId: String?
    // Source of this representative recording (e.g. "Microphone", "Zoom")
    let audioSource: String?
    // For grouped (multi-source) meetings: one entry per member recording.
    // nil/single member means this is a standalone (or legacy) meeting.
    let members: [MeetingMember]?
    
    enum CodingKeys: String, CodingKey {
        case id
        case name
        case purpose
        case participants
        case startTime = "start_time"
        case endTime = "end_time"
        case durationSeconds = "duration_seconds"
        case audioPath = "audio_path"
        case transcriptPath = "transcript_path"
        case isPostProcessed = "is_post_processed"
        case analysisSummary = "analysis_summary"
        case sessionId = "session_id"
        case audioSource = "audio_source"
        case members
    }
    
    /// Display title with fallback to name
    var displayTitle: String {
        return name
    }
    
    /// Formatted date for display (e.g., "2026-01-23 3:45 pm")
    var formattedDate: String {
        DateFormattingUtils.formatTimestamp(startTime)
    }
    
    /// Formatted duration (e.g., "45m 30s")
    var formattedDuration: String {
        guard let duration = durationSeconds else {
            return "Unknown"
        }
        
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        
        if minutes > 0 {
            return "\(minutes)m \(seconds)s"
        } else {
            return "\(seconds)s"
        }
    }
    
    /// Short formatted duration for list display (e.g., "45m")
    var shortFormattedDuration: String {
        guard let duration = durationSeconds else {
            return "—"
        }
        
        let minutes = Int(duration) / 60
        
        if minutes > 0 {
            return "\(minutes)m"
        } else {
            let seconds = Int(duration)
            return "\(seconds)s"
        }
    }
    
    /// Style-aware display date that honors the user's date display preference
    /// (relative vs absolute). Falls back to the raw string if parsing fails.
    var displayDate: String {
        return DateFormattingUtils.formatTimestamp(startTime)
    }

    /// Relative date string (e.g., "Today", "Yesterday", "Nov 28")
    var relativeDateString: String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        
        guard let date = formatter.date(from: startTime) else {
            // Fallback: try without fractional seconds
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: startTime) else {
                return formattedDate
            }
            return formatRelativeDate(date)
        }
        
        return formatRelativeDate(date)
    }
    
    /// Format relative date
    private func formatRelativeDate(_ date: Date) -> String {
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
}

// MARK: - Meeting Member

/// One member recording of a grouped (multi-source) meeting.
struct MeetingMember: Codable, Identifiable {
    let id: String
    let source: String?
    let isPostProcessed: Bool
    // Resume/grouping detail (optional; legacy members omit these).
    let startTime: String?
    let durationSeconds: Double?
    let timelineOffsetSeconds: Double?
    let recordingPartIndex: Int?
    
    enum CodingKeys: String, CodingKey {
        case id
        case source
        case isPostProcessed = "is_post_processed"
        case startTime = "start_time"
        case durationSeconds = "duration_seconds"
        case timelineOffsetSeconds = "timeline_offset_seconds"
        case recordingPartIndex = "recording_part_index"
    }

    /// Absolute recording-start instant parsed from `startTime`, used to align
    /// multi-track members onto a shared session origin (cross-track skew
    /// correction). Returns nil when no/invalid start_time is present.
    var startDate: Date? {
        guard let startTime = startTime else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: startTime) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: startTime)
    }
}

// MARK: - Analysis Summary

/// Sidebar-facing summary of a meeting's analysis history.
struct AnalysisSummary: Codable {
    let count: Int
    let latestFilename: String
    let latestTimestamp: String
    let pendingActionCount: Int?

    enum CodingKeys: String, CodingKey {
        case count
        case latestFilename = "latest_filename"
        case latestTimestamp = "latest_timestamp"
        case pendingActionCount = "pending_action_count"
    }
}

// MARK: - Analysis Metadata Entry

/// Represents metadata for a saved meeting analysis
struct AnalysisMetadataEntry: Codable, Identifiable {
    var id: String { filename }
    let timestamp: String
    let filename: String
    let modes: [String]
    let modelUsed: String
    
    enum CodingKeys: String, CodingKey {
        case timestamp
        case filename
        case modes
        case modelUsed = "model_used"
    }
    
    /// Formatted date for display
    var formattedDate: String {
        DateFormattingUtils.formatTimestamp(utcTimestamp)
    }

    /// Analysis metadata is persisted by the backend in UTC. Older records omit
    /// the UTC designator, so normalize only those legacy timestamps before the
    /// shared formatter converts them to the user's local timezone.
    private var utcTimestamp: String {
        guard !timestamp.hasSuffix("Z"),
              timestamp.range(
                of: "[+-]\\d{2}:?\\d{2}$",
                options: .regularExpression
              ) == nil else {
            return timestamp
        }
        return "\(timestamp)Z"
    }
    
    /// Modes display string (comma-separated with proper formatting)
    var modesDisplay: String {
        // Convert mode IDs to display names
        let displayNames = modes.map { mode -> String in
            switch mode {
            case "action_items": return "Action Items"
            case "summary": return "Summary"
            case "decisions": return "Decisions"
            case "questions_answers": return "Q&A"
            case "sentiment_analysis": return "Sentiment"
            case "custom_analysis": return "Custom"
            default: return mode.capitalized
            }
        }
        return displayNames.joined(separator: ", ")
    }
    
    /// Short model name for table display
    var shortModelName: String {
        // Extract last part of model name for display
        let components = modelUsed.components(separatedBy: "-")
        if components.count > 1 {
            return components.suffix(2).joined(separator: "-")
        }
        return modelUsed
    }
}

// MARK: - Backend Response Types

/// Backend response for meeting transcript segments
struct BackendTranscriptSegment: Codable {
    let start: Double
    let end: Double
    let text: String
    let speakerValue: SpeakerValue?
    let isInterim: Bool?
    
    enum CodingKeys: String, CodingKey {
        case start
        case end
        case text
        case speakerValue = "speaker"
        case isInterim = "is_interim"
    }
    
    // Speaker can be either String or Int from backend
    enum SpeakerValue: Codable {
        case string(String)
        case int(Int)
        
        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let intValue = try? container.decode(Int.self) {
                self = .int(intValue)
            } else if let stringValue = try? container.decode(String.self) {
                self = .string(stringValue)
            } else {
                throw DecodingError.typeMismatch(
                    SpeakerValue.self,
                    DecodingError.Context(
                        codingPath: decoder.codingPath,
                        debugDescription: "Expected String or Int for speaker"
                    )
                )
            }
        }
        
        func encode(to encoder: Encoder) throws {
            var container = encoder.singleValueContainer()
            switch self {
            case .string(let value):
                try container.encode(value)
            case .int(let value):
                try container.encode(value)
            }
        }
        
        var stringValue: String? {
            switch self {
            case .string(let value):
                return value
            case .int(let value):
                // Convert -1 to nil, otherwise convert to "Speaker X"
                return value >= 0 ? "Speaker \(value + 1)" : nil
            }
        }
    }
}

/// Backend response for meeting transcript
struct BackendMeetingTranscript: Codable {
    let meetingId: String
    let segments: [BackendTranscriptSegment]
    
    enum CodingKeys: String, CodingKey {
        case meetingId = "meeting_id"
        case segments
    }
}

