import Foundation

// MARK: - AudioSource
enum AudioSource: String, Codable {
    case microphone = "Microphone"
    case systemAudio = "SystemAudio"

    var displayName: String {
        switch self {
        case .microphone: return "Microphone"
        case .systemAudio: return "System Audio"
        }
    }
}

enum SystemAudioCaptureMode: String {
    case none
    case selectedProcess
    case globalOutput
}

enum MeetingSearchTermMode: String, Codable {
    case and
    case or
}

enum MeetingProcessingFilter: String, Codable {
    case any
    case complete
    case incomplete
}

enum MeetingAnalysisFilter: String, Codable {
    case any
    case hasAnalysis = "has_analysis"
    case noAnalysis = "no_analysis"
}

struct MeetingHistorySearchFilters: Codable, Equatable {
    var queryMode: MeetingSearchTermMode = .and
    var name: String = ""
    var nameMode: MeetingSearchTermMode = .and
    var purpose: String = ""
    var purposeMode: MeetingSearchTermMode = .and
    var participants: String = ""
    var participantsMode: MeetingSearchTermMode = .and
    var transcript: String = ""
    var transcriptMode: MeetingSearchTermMode = .and
    var source: String = ""
    var sourceMode: MeetingSearchTermMode = .and
    var startDate: String?
    var endDate: String?
    var processing: MeetingProcessingFilter = .any
    var analysis: MeetingAnalysisFilter = .any

    var isActive: Bool {
        [name, purpose, participants, transcript, source].contains { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            || startDate != nil
            || endDate != nil
            || processing != .any
            || analysis != .any
    }

    static let cleared = MeetingHistorySearchFilters()
}

enum WindowRetranscriptionPhase: Equatable {
    case running
    case applying
    case completed
    case failed
}

struct WindowRetranscriptionStatus: Equatable, Identifiable {
    let id: UUID
    let source: AudioSource
    let start: Double
    let end: Double
    let phase: WindowRetranscriptionPhase
    let message: String

    init(
        id: UUID = UUID(),
        source: AudioSource,
        start: Double,
        end: Double,
        phase: WindowRetranscriptionPhase,
        message: String
    ) {
        self.id = id
        self.source = source
        self.start = start
        self.end = end
        self.phase = phase
        self.message = message
    }

    var isInFlight: Bool {
        phase == .running || phase == .applying
    }
}

// MARK: - TranscriptionLine
/// Represents a single line of transcription with speaker attribution
struct TranscriptionLine: Identifiable, Codable {
    let id: String
    var text: String  // Mutable so we can append new tokens
    let speakerID: String?  // "speaker0", "speaker1", etc. OR source name ("Microphone", "Zoom")
    let isInterim: Bool
    let start: String?
    let end: String?
    let diff: Double?
    let timelineStartSeconds: Double?
    let timelineEndSeconds: Double?
    var source: AudioSource?  // Which audio source this line came from (set locally, not from backend)
    var lineComplete: Bool  // True if this token batch completes a line (silence detected)
    
    // Computed property to extract speaker number for display (e.g., "speaker0" -> 1)
    var speakerNumber: Int? {
        guard let speakerID = speakerID,
              speakerID.hasPrefix("speaker"),
              let num = Int(speakerID.replacingOccurrences(of: "speaker", with: "")) else {
            return nil
        }
        return num + 1  // Convert 0-based to 1-based for display
    }

    var displayStart: String? {
        if let timelineStartSeconds {
            return Self.formatElapsedSeconds(timelineStartSeconds)
        }
        return start
    }

    private static func formatElapsedSeconds(_ seconds: Double) -> String {
        let totalSeconds = max(0, Int(seconds.rounded()))
        let hours = totalSeconds / 3600
        let minutes = (totalSeconds % 3600) / 60
        let seconds = totalSeconds % 60

        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%d:%02d", minutes, seconds)
    }
    
    enum CodingKeys: String, CodingKey {
        case text
        case speaker
        case isInterim = "is_interim"
        case start
        case end
        case diff
        case timelineStartSeconds = "timeline_start_seconds"
        case timelineEndSeconds = "timeline_end_seconds"
        case source
        case lineComplete = "line_complete"
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        
        // Generate a unique ID locally
        self.id = UUID().uuidString
        
        // Decode the rest of the fields
        self.text = try container.decode(String.self, forKey: .text)
        
        // Speaker can be String ("speaker0"), Int (-2 for silence, or other ints), or nil
        if let speakerString = try? container.decode(String.self, forKey: .speaker) {
            self.speakerID = speakerString
        } else if let speakerInt = try? container.decode(Int.self, forKey: .speaker) {
            // Convert int to string (e.g., -2 for silence, or convert to speakerN format if positive)
            if speakerInt == -2 {
                self.speakerID = nil  // Silence - don't show speaker badge
            } else if speakerInt > 0 {
                self.speakerID = "speaker\(speakerInt - 1)"  // Convert 1-based to 0-based: 1 -> speaker0
            } else {
                self.speakerID = nil  // Other negative values - don't show
            }
        } else {
            self.speakerID = nil
        }
        
        self.isInterim = try container.decodeIfPresent(Bool.self, forKey: .isInterim) ?? false
        self.start = try container.decodeIfPresent(String.self, forKey: .start)
        self.end = try container.decodeIfPresent(String.self, forKey: .end)
        self.diff = try container.decodeIfPresent(Double.self, forKey: .diff)
        self.timelineStartSeconds = try container.decodeIfPresent(Double.self, forKey: .timelineStartSeconds)
        self.timelineEndSeconds = try container.decodeIfPresent(Double.self, forKey: .timelineEndSeconds)
        self.source = try container.decodeIfPresent(AudioSource.self, forKey: .source)
        self.lineComplete = try container.decodeIfPresent(Bool.self, forKey: .lineComplete) ?? false
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(text, forKey: .text)
        try container.encodeIfPresent(speakerID, forKey: .speaker)
        try container.encode(isInterim, forKey: .isInterim)
        try container.encodeIfPresent(start, forKey: .start)
        try container.encodeIfPresent(end, forKey: .end)
        try container.encodeIfPresent(diff, forKey: .diff)
        try container.encodeIfPresent(timelineStartSeconds, forKey: .timelineStartSeconds)
        try container.encodeIfPresent(timelineEndSeconds, forKey: .timelineEndSeconds)
        try container.encodeIfPresent(source, forKey: .source)
    }
    
    // Keep the manual initializer for preview data
    init(id: String, text: String, speakerID: String?, isInterim: Bool, start: String?, end: String?, diff: Double?, timelineStartSeconds: Double? = nil, timelineEndSeconds: Double? = nil, source: AudioSource? = nil, lineComplete: Bool = false) {
        self.id = id
        self.text = text
        self.speakerID = speakerID
        self.isInterim = isInterim
        self.start = start
        self.end = end
        self.diff = diff
        self.timelineStartSeconds = timelineStartSeconds
        self.timelineEndSeconds = timelineEndSeconds
        self.source = source
        self.lineComplete = lineComplete
    }
}

// MARK: - LiveTranscriptionResponse
/// WebSocket response containing transcription updates
struct LiveTranscriptionResponse: Codable {
    let lines: [TranscriptionLine]
    let buffer_transcription: String?
    let buffer_diarization: String?
    let remaining_time_transcription: Double
    let remaining_time_diarization: Double
    // Event-driven batched transcription fields
    let state: String?
    let accumulated_duration: Double?
    let trigger_reason: String?
    
    enum CodingKeys: String, CodingKey {
        case lines
        case buffer_transcription
        case buffer_diarization
        case remaining_time_transcription
        case remaining_time_diarization
        case state
        case accumulated_duration
        case trigger_reason
    }
}

enum TranscriptionState: String, Codable {
    case loadingModels
    case idle
    case listening
    case transcribing
}

enum MicrophoneInputRecoveryState: Equatable {
    case idle
    case reconnecting
    case failed(message: String)
}

enum ConnectionState {
    case ready
    case recording
    case error
    case connecting
}

// MARK: - AudioError
/// Errors related to audio recording
enum AudioError: LocalizedError {
    case engineSetupFailed
    case invalidFormat
    case recordingFailed
    case permissionDenied
    
    var errorDescription: String? {
        switch self {
        case .engineSetupFailed:
            return "Failed to set up audio engine"
        case .invalidFormat:
            return "Failed to create audio format"
        case .recordingFailed:
            return "Failed to start recording"
        case .permissionDenied:
            return "System audio permission denied"
        }
    }

    var localizedDescription: String {
        errorDescription ?? "Audio capture failed"
    }
}

// MARK: - WebSocketError
/// Errors related to WebSocket connection
enum WebSocketError: Error {
    case invalidURL
    case invalidResponse
    case invalidSettings
    
    var localizedDescription: String {
        switch self {
        case .invalidURL:
            return "Invalid URL provided"
        case .invalidResponse:
            return "Invalid response from server"
        case .invalidSettings:
            return "Transcription settings not available"
        }
    }
}

// MARK: - AudioStats
/// Statistics for audio level monitoring
struct AudioStats {
    var maxAmplitude: Float = 0
    var totalAmplitude: Double = 0
    var averageAmplitude: Double = 0
    var nonZeroSamples: Int = 0
    var nonZeroPercentage: Double = 0
    var highLevelSamples: Int = 0
    var midLevelSamples: Int = 0
    var lowLevelSamples: Int = 0
}

// MARK: - SystemAudioCaptureRequest
/// Helper for system audio capture permission (macOS 14+)
@available(macOS 14.0, *)
class SystemAudioCaptureRequest {
    // In the working implementation, there is no explicit permission request.
    // Instead, the permission is implicitly triggered when the ProcessTapRecorder is used.
    // We'll mimic that approach instead of our current one.
    
    func requestPermission() async -> Bool {
        return true  // Always return true since permission will be handled by ProcessTapRecorder
    }
}

