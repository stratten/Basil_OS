import Foundation

enum TranscriptionApiModelsPayloadBuilder {
    static let catalog: [(id: String, displayName: String, description: String)] = [
        (
            "openai-whisper-1",
            "Whisper (OpenAI API)",
            "OpenAI's hosted Whisper model -- proven, reliable transcription"
        ),
        (
            "openai-gpt-4o-transcribe",
            "GPT-4o Transcribe (OpenAI API)",
            "GPT-4o-based transcription -- higher accuracy, higher cost"
        ),
        (
            "openai-gpt-4o-mini-transcribe",
            "GPT-4o Mini Transcribe (OpenAI API)",
            "Smaller GPT-4o transcription -- good balance of cost and quality"
        ),
    ]

    static func makeModelSummaries(enabledModels: [TranscriptionAPIModelInfo]) -> [[String: Any]] {
        let enabledIds = Set(enabledModels.map { $0.id })
        return catalog.map { entry in
            [
                "id": entry.id,
                "displayName": entry.displayName,
                "description": entry.description,
                "enabled": enabledIds.contains(entry.id),
            ]
        }
    }
}
