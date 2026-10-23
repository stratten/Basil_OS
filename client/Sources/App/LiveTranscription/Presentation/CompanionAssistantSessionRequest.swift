import Foundation

/// The validated payload of the web layer's `openCompanionAssistantSession` intent: the instruction of an approved Companion proposal and the researched answer it came from.
struct CompanionAssistantSessionRequest: Equatable {
    static let maxInstructionCharacters = 2_000
    static let maxContextCharacters = 4_000
    /// The session start needs some context text, so a proposal without a researched answer sends this sentence instead.
    static let fallbackContext = "Opened from a Notetaker Companion suggestion."

    let instruction: String
    let contextText: String

    init?(payload: [String: Any]) {
        guard let rawInstruction = payload["instruction"] as? String else { return nil }
        let instruction = rawInstruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !instruction.isEmpty, instruction.count <= Self.maxInstructionCharacters else { return nil }

        let context: String
        if let rawContext = payload["contextText"] {
            guard let text = rawContext as? String else { return nil }
            context = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(Self.maxContextCharacters))
        } else {
            context = ""
        }

        self.instruction = instruction
        self.contextText = context.isEmpty ? Self.fallbackContext : context
    }
}
