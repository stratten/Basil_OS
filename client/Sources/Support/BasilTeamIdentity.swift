import Foundation

/// Central source for user-facing Basil team member labels.
///
/// Stable internal concepts should use capability names such as
/// `AssistantSession` and `AgentTask`. Character names like "Dill" and
/// "Paprika" belong here so pilot-feedback changes stay localized to this
/// catalog instead of spreading through routes, models, and controllers.
enum BasilTeamIdentity {
    struct TeamMember {
        let displayName: String
        let roleLabel: String
        let shortDescription: String
    }

    static let assistantSession = TeamMember(
        displayName: "Dill",
        roleLabel: "Writing partner",
        shortDescription: "Helps you draft, summarize, respond, research, and find the right words in the moment."
    )

    static let agentTask = TeamMember(
        displayName: "Paprika",
        roleLabel: "Side-quest helper",
        shortDescription: "Takes a task, works through the steps, and brings back a result."
    )

}
