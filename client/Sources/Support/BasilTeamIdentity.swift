import Foundation

/// Central source for user-facing Basil team member labels.
///
/// Stable internal concepts use capability names such as `AssistantSession` and `AgentTask`; those identifiers are never user-visible. Character names like "Dill" and "Paprika" and their plain-language descriptors live here so naming changes stay localized to this catalog.
///
/// Quick Assist (Dill) answers each request, including each refinement, in a single model turn, even when that turn performs research. Agent (Paprika) runs a multi-step loop with tools, progress, and approvals, and can work on many tasks at once.
enum BasilTeamIdentity {
    struct TeamMember {
        let displayName: String
        let descriptor: String
        let shortDescription: String

        /// Friendly name with the descriptor as a parenthetical, for entry points and identity surfaces.
        var pairedName: String { "\(displayName) (\(descriptor))" }
    }

    static let assistantSession = TeamMember(
        displayName: "Dill",
        descriptor: "Quick Assist",
        shortDescription: "Helps you draft, summarize, respond, research, and find the right words in the moment."
    )

    static let agentTask = TeamMember(
        displayName: "Paprika",
        descriptor: "Agent",
        shortDescription: "Takes a task, works through the steps, and brings back a result."
    )

}
