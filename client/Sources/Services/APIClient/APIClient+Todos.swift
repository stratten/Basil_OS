import Foundation

struct PromoteMeetingProposalRequest: Codable {
    let meetingId: String
    let filename: String
    let proposalId: String
    let sourceTask: String
    let suggestedAgentTask: String
    let whyBasilCanHelp: String
    let sourceContext: String?

    enum CodingKeys: String, CodingKey {
        case meetingId = "meeting_id"
        case filename
        case proposalId = "proposal_id"
        case sourceTask = "source_task"
        case suggestedAgentTask = "suggested_agent_task"
        case whyBasilCanHelp = "why_basil_can_help"
        case sourceContext = "source_context"
    }
}

struct TodoWorkAttemptResponse: Codable {
    let agentTaskId: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case agentTaskId = "agent_task_id"
        case status
    }
}

struct TodoItemDetailResponse: Codable {
    let id: String
    let status: String
    let revision: Int
    let workerAttempts: [TodoWorkAttemptResponse]

    enum CodingKeys: String, CodingKey {
        case id
        case status
        case revision
        case workerAttempts = "worker_attempts"
    }
}

struct TodoWorkerLaunchResponse: Codable {
    let item: TodoItemDetailResponse
    let agentTaskId: String

    enum CodingKeys: String, CodingKey {
        case item
        case agentTaskId = "agent_task_id"
    }
}

struct LaunchTodoWorkerRequest: Codable {
    let expectedRevision: Int
}

extension APIClient {
    /// Promotes an accepted meeting-suggested action into a durable To-Do.
    /// Sends only the fields required for idempotent source attribution;
    /// the backend owns dedupe via `(meeting_id, filename, proposal_id)`.
    func promoteMeetingProposalToTodo(
        meetingId: String,
        filename: String,
        proposal: MeetingActionProposal,
        suggestedAgentTask: String
    ) async throws -> TodoItemDetailResponse {
        let body = PromoteMeetingProposalRequest(
            meetingId: meetingId,
            filename: filename,
            proposalId: proposal.id,
            sourceTask: proposal.sourceTask,
            suggestedAgentTask: suggestedAgentTask,
            whyBasilCanHelp: proposal.whyBasilCanHelp,
            sourceContext: proposal.sourceContext
        )
        let data = try await postForData("/api/v1/todos/meeting-proposals/promote", body)
        return try JSONDecoder().decode(TodoItemDetailResponse.self, from: data)
    }

    func launchTodoWorker(todoId: String, expectedRevision: Int) async throws -> TodoWorkerLaunchResponse {
        let body = LaunchTodoWorkerRequest(expectedRevision: expectedRevision)
        let data = try await postForData("/api/v1/todos/items/\(todoId)/workers", body)
        return try JSONDecoder().decode(TodoWorkerLaunchResponse.self, from: data)
    }

    func getTodoItemDetail(todoId: String) async throws -> TodoItemDetailResponse {
        let data = try await get("/api/v1/todos/items/\(todoId)")
        return try JSONDecoder().decode(TodoItemDetailResponse.self, from: data)
    }
}
