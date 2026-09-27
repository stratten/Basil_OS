import Foundation

struct ContinueSessionRequest: Codable {
    let agentTaskId: String
    let userInput: String
    let metadata: [String: String]?

    enum CodingKeys: String, CodingKey {
        case agentTaskId = "agent_task_id"
        case userInput = "user_input"
        case metadata
    }

    init(agentTaskId: String, userInput: String, metadata: [String: String]? = nil) {
        self.agentTaskId = agentTaskId
        self.userInput = userInput
        self.metadata = metadata
    }
}

struct ContinueSessionResponse: Codable {
    let success: Bool
    let message: String
    let requiresMoreInput: Bool
    let result: String?

    enum CodingKeys: String, CodingKey {
        case success
        case message
        case requiresMoreInput = "requires_more_input"
        case result
    }
}

struct AgentTaskCancelResponse: Codable {
    let success: Bool
    let message: String
    let finalizedViaAgent: Bool
    let agentTaskId: String
}
