import Foundation

/// Pure decision logic for meeting post-processing automation (auto-retranscribe
/// on stop and auto-analyze on complete). Extracted from the view model so the
/// sequencing can be unit-tested without the audio/recording machinery.
enum PostProcessingAutomation {
    /// An ordered automation step to run after a meeting stops/completes.
    enum Step: Equatable {
        case retranscribe
        case analyze
    }

    /// Whether stopping a recording should kick off automatic re-transcription.
    /// Requires the feature enabled and that the meeting actually captured audio
    /// (an empty meeting has nothing to upgrade).
    static func shouldAutoRetranscribeOnStop(enabled: Bool, hasRecordedAudio: Bool) -> Bool {
        enabled && hasRecordedAudio
    }

    /// Returns the model used for automatic post-processing at recording start.
    /// A per-session picker choice wins; otherwise the configured transcription
    /// model ID is already valid for the backend execution endpoints.
    static func executionModel(
        configuredModelID: String,
        sessionModel: String
    ) -> String {
        let existing = sessionModel.trimmingCharacters(in: .whitespacesAndNewlines)
        if !existing.isEmpty {
            return existing
        }
        return configuredModelID.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Cadence scheduling is independent of picker-catalog readiness. A tick
    /// defers without advancing a checkpoint if its execution model is absent.
    static func shouldArmMidRecordingCadence(enabled: Bool) -> Bool {
        enabled
    }

    /// Ordered automation plan given the resolved (post-override) flags.
    ///
    /// - `timing == "before"` runs analysis ahead of re-transcription, but only
    ///   when both are enabled; otherwise each enabled step runs standalone.
    static func plan(
        autoRetranscribe: Bool,
        autoAnalyze: Bool,
        timing: String
    ) -> [Step] {
        switch (autoRetranscribe, autoAnalyze) {
        case (true, true):
            return timing == "before" ? [.analyze, .retranscribe] : [.retranscribe, .analyze]
        case (true, false):
            return [.retranscribe]
        case (false, true):
            return [.analyze]
        case (false, false):
            return []
        }
    }
}
