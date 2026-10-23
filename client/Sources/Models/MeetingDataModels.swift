import Foundation
import SwiftUI

// MARK: - Meeting Data Structures

struct Meeting: Codable, Identifiable {
    let id: String
    let name: String
    let purpose: String?
    let startTime: Date
    let endTime: Date?
    let participants: [String]?
    var isActive: Bool
    let meetingNotes: String?
    
    // Computed properties
    var duration: TimeInterval? {
        guard let end = endTime else { return nil }
        return end.timeIntervalSince(startTime)
    }
    
    var formattedDuration: String {
        guard let duration = duration else { return "In progress" }
        
        let hours = Int(duration) / 3600
        let minutes = (Int(duration) % 3600) / 60
        let seconds = Int(duration) % 60
        
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            return String(format: "%d:%02d", minutes, seconds)
        }
    }
    
    var isCompleted: Bool {
        return endTime != nil
    }
}

// MARK: - Meeting Transcript Structures

struct MeetingTranscript: Codable, Identifiable {
    let id: String
    let meetingId: String
    let transcriptSegments: [TranscriptSegment]
    let createdAt: Date
    let processingStatus: ProcessingStatus
    
    enum ProcessingStatus: String, Codable {
        case inProgress = "in_progress"
        case completed = "completed"
        case failed = "failed"
    }
}

struct TranscriptSegment: Codable, Identifiable {
    let id: String
    let speakerId: String?
    let speakerName: String?
    let text: String
    let confidence: Double
    let startTime: TimeInterval
    let endTime: TimeInterval
    let audioSource: AudioSource
    let applicationName: String?
    
    enum AudioSource: String, Codable {
        case localMicrophone = "local_mic"
        case systemAudio = "system_audio"
        case unknown = "unknown"
        
        var displayName: String {
            switch self {
            case .localMicrophone:
                return "Microphone"
            case .systemAudio:
                return "System Audio"
            case .unknown:
                return "Unknown Source"
            }
        }
        
        var color: Color {
            switch self {
            case .localMicrophone:
                return Color.blue
            case .systemAudio:
                return Color.green
            case .unknown:
                return Color.gray
            }
        }
    }
    
    var duration: TimeInterval {
        return endTime - startTime
    }
    
    var formattedTimestamp: String {
        let startMinutes = Int(startTime) / 60
        let startSeconds = Int(startTime) % 60
        
        return String(format: "%02d:%02d", startMinutes, startSeconds)
    }
    
    // Returns source display name with application if available
    var sourceDisplayName: String {
        if audioSource == .systemAudio, let appName = applicationName, !appName.isEmpty {
            return "\(appName)"
        }
        return audioSource.displayName
    }
}

// MARK: - WebSocket Communication Models

/// WebSocket message for meeting operations
struct MeetingWebSocketMessage: Codable {
    let type: MessageType
    let data: [String: AnyCodable]?
    
    enum MessageType: String, Codable {
        case initMeeting = "init_meeting"
        case startMeeting = "start_meeting"
        case endMeeting = "end_meeting"
        case pauseMeeting = "pause_meeting"
        case resumeMeeting = "resume_meeting"
        case processMeeting = "process_meeting"
        case meetingStatus = "meeting_status"
        case transcriptSegment = "transcript_segment"
        case speakerDetected = "speaker_detected"
        case processingCompleted = "processing_completed"
        case audioData = "audio_data"
        case error = "error"
    }
    
    init(type: MessageType, data: [String: Any]? = nil) {
        self.type = type
        if let data = data {
            self.data = data.mapValues { AnyCodable($0) }
        } else {
            self.data = nil
        }
    }
}

/// Structure for meeting audio data with source information
struct MeetingAudioData: Codable {
    let meetingId: String
    let audioSource: TranscriptSegment.AudioSource
    let timestamp: TimeInterval
    let metadata: MeetingMetadata?
    let applicationName: String?
    
    struct MeetingMetadata: Codable {
        let meetingName: String?
        let purpose: String?
        let participants: [String]?
        let currentSpeaker: String?
    }
    
    init(meetingId: String, audioSource: TranscriptSegment.AudioSource, timestamp: TimeInterval, metadata: MeetingMetadata?, applicationName: String? = nil) {
        self.meetingId = meetingId
        self.audioSource = audioSource
        self.timestamp = timestamp
        self.metadata = metadata
        self.applicationName = applicationName
    }
}

/// Response for meeting transcription segments from backend
struct MeetingTranscriptionResponse: Codable {
    let success: Bool
    let segments: [TranscriptSegment]?
    let error: String?
}

/// Wrapper for Codable Any values - used for flexible WebSocket messages
struct AnyCodable: Codable {
    let value: Any
    
    init(_ value: Any) {
        self.value = value
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        
        if container.decodeNil() {
            self.value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            self.value = bool
        } else if let int = try? container.decode(Int.self) {
            self.value = int
        } else if let double = try? container.decode(Double.self) {
            self.value = double
        } else if let string = try? container.decode(String.self) {
            self.value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            self.value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            self.value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "AnyCodable cannot decode value")
        }
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        
        switch self.value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            let context = EncodingError.Context(codingPath: container.codingPath, 
                                               debugDescription: "AnyCodable cannot encode value")
            throw EncodingError.invalidValue(value, context)
        }
    }
}

// MARK: - API Response Structures

struct MeetingListResponse: Codable {
    let success: Bool
    let meetings: [Meeting]
    let error: String?
}

struct MeetingResponse: Codable {
    let success: Bool
    let meeting: Meeting?
    let error: String?
}

struct MeetingTranscriptResponse: Codable {
    let success: Bool
    let transcript: MeetingTranscript?
    let error: String?
}

// MARK: - Meeting Processing Results

struct MeetingProcessingResult: Codable, Identifiable {
    let id: String
    let meetingId: String
    let resultType: ResultType
    let content: String
    let createdAt: Date
    
    enum ResultType: String, Codable {
        case actionItems = "action_items"
        case summary = "summary"
        case minutes = "minutes"
        case keyPoints = "key_points"
        case decisions = "decisions"
    }
}

struct MeetingProcessingResponse: Codable {
    let success: Bool
    let result: MeetingProcessingResult?
    let error: String?
}

struct MeetingProcessingListResponse: Codable {
    let success: Bool
    let results: [MeetingProcessingResult]
    let error: String?
}

// MARK: - Speaker Identification

struct Speaker: Codable, Identifiable {
    let id: String
    let name: String?
    let voiceSignature: Data? // Voice fingerprint for identification
    
    // Additional properties for speaker identification
    let confidenceScore: Double?
    let isLocalSpeaker: Bool?
    let firstDetectedAt: Date?
    let lastDetectedAt: Date?
}

struct SpeakerDiarizationRequest: Codable {
    let meetingId: String
    let audioData: Data
    let audioSource: TranscriptSegment.AudioSource
    let knownSpeakers: [Speaker]?
}

struct SpeakerDiarizationResponse: Codable {
    let success: Bool
    let speakerId: String?
    let speakerName: String?
    let confidence: Double
    let error: String?
    let isNewSpeaker: Bool
}

// MARK: - Meeting Settings

struct MeetingSettings: Codable {
    var autoStartTranscription: Bool = true
    var enableSpeakerIdentification: Bool = true
    var saveAudio: Bool = true
    var postMeetingProcessingEnabled: Bool = true
    var defaultProcessingTypes: [MeetingProcessingResult.ResultType] = [.actionItems, .summary]
    var widgetSize: [CGFloat]? // Width, height
    var widgetPosition: [CGFloat]? // X, Y, screenID
}

struct MeetingSettingsResponse: Codable {
    let success: Bool
    let settings: MeetingSettings
    let error: String?
} 