import Foundation

struct TranscriptionHistoryResponse: Codable {
    let success: Bool
    let transcriptions: [TranscriptionRecord]
    let error: String?
}

/// Lifecycle state reported by the backend for a transcription row.
/// Pending rows are in-flight; failed rows surface ``errorMessage``
/// so the UI can explain why (e.g. network outage) and offer a retry.
enum TranscriptionStatus: String, Codable {
    case pending
    case completed
    case failed

    /// Safe fallback for older backend versions that predate the
    /// status column -- legacy rows are treated as completed.
    static func fromRaw(_ raw: String?) -> TranscriptionStatus {
        guard let raw else { return .completed }
        return TranscriptionStatus(rawValue: raw) ?? .completed
    }
}

struct TranscriptionRecord: Codable, Identifiable {
    let id: String
    let timestamp: String
    let transcriptionText: String
    let modelName: String
    let audioFilePath: String
    let durationSeconds: Double?
    let language: String
    let createdAt: String?
    let lastTranscribedAt: String?
    
    // Context information
    let appName: String?
    let windowTitle: String?
    let taskCategory: String?
    
    // User interaction
    let wasEdited: Bool
    let editDistance: Int?
    let editedText: String?
    
    // Performance metrics
    let confidenceScore: Double?
    let processingTimeMs: Int?
    let userRating: Int?
    let userFeedback: String?
    
    // Relationships
    let sessionId: String?
    let relatedActivityId: String?
    
    // Follow-up actions
    let actionTaken: String?

    // Lifecycle state (pending / completed / failed) and the failure
    // reason associated with a failed row. Stored as String here so
    // missing fields from older backends decode cleanly; use
    // ``statusKind`` to get the enum.
    let status: String?
    let errorMessage: String?

    // Computed properties
    var formattedDate: String {
        DateFormattingUtils.formatTimestamp(timestamp)
    }

    var formattedLastTranscribedDate: String? {
        guard let lastTranscribedAt,
              !lastTranscribedAt.isEmpty,
              lastTranscribedAt != timestamp else {
            return nil
        }
        return DateFormattingUtils.formatTimestamp(lastTranscribedAt)
    }
    
    var displayText: String {
        if let edited = editedText, wasEdited {
            return edited
        }
        return transcriptionText
    }
    
    var formattedDuration: String {
        guard let duration = durationSeconds else { return "Unknown" }
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        return String(format: "%d:%02d", minutes, seconds)
    }

    var statusKind: TranscriptionStatus {
        TranscriptionStatus.fromRaw(status)
    }

    var isFailed: Bool { statusKind == .failed }
    var isPending: Bool { statusKind == .pending }
    
    /// Create a copy with updated transcription text (for retranscription)
    func withUpdatedText(_ newText: String) -> TranscriptionRecord {
        return TranscriptionRecord(
            id: id,
            timestamp: timestamp,
            transcriptionText: newText,
            modelName: modelName,
            audioFilePath: audioFilePath,
            durationSeconds: durationSeconds,
            language: language,
            createdAt: createdAt,
            lastTranscribedAt: lastTranscribedAt,
            appName: appName,
            windowTitle: windowTitle,
            taskCategory: taskCategory,
            wasEdited: false,  // Reset since this is fresh transcription
            editDistance: nil,
            editedText: nil,
            confidenceScore: confidenceScore,
            processingTimeMs: processingTimeMs,
            userRating: userRating,
            userFeedback: userFeedback,
            sessionId: sessionId,
            relatedActivityId: relatedActivityId,
            actionTaken: actionTaken,
            status: TranscriptionStatus.completed.rawValue,
            errorMessage: nil
        )
    }
    
    enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case transcriptionText = "transcription_text"
        case modelName = "model_name"
        case audioFilePath = "audio_file_path"
        case durationSeconds = "duration_seconds"
        case language
        case createdAt = "created_at"
        case lastTranscribedAt = "last_transcribed_at"
        case appName = "app_name"
        case windowTitle = "window_title"
        case taskCategory = "task_category"
        case wasEdited = "was_edited"
        case editDistance = "edit_distance"
        case editedText = "edited_text"
        case confidenceScore = "confidence_score"
        case processingTimeMs = "processing_time_ms"
        case userRating = "user_rating"
        case userFeedback = "user_feedback"
        case sessionId = "session_id"
        case relatedActivityId = "related_activity_id"
        case actionTaken = "action_taken"
        case status
        case errorMessage = "error_message"
    }
} 