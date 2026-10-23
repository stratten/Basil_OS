import Foundation

// MARK: - AgentTask Processing Data Models
struct AgentTaskExampleData: Codable {
    let examples: [String]
}

// MARK: - AgentTask Response Data Models
struct AgentTaskResponse: Codable {
    let success: Bool
    let operation: String
    let confidence: Double
    let reasoning: String
    let message: String
    let processingTime: Double
    let agentTaskId: String
    let data: String?
    let error: String?
    
    enum CodingKeys: String, CodingKey {
        case success
        case operation
        case confidence
        case reasoning
        case message
        case processingTime = "processing_time"
        case agentTaskId = "agent_task_id"
        case data
        case error
    }
}

// MARK: - AgentTask Streaming Data Models
struct AgentTaskStreamingChunk: Codable {
    let stage: String?
    let operation: String?
    let agentTask: String?
    let suggestion_token: String?
    let suggestion_partial: String?
    let summary_token: String?
    let summary_partial: String?
    let activities: [String]?
    let complete: Bool?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case stage
        case operation
        case agentTask = "agent_task"
        case suggestion_token
        case suggestion_partial
        case summary_token
        case summary_partial
        case activities
        case complete
        case error
    }
}

// MARK: - AgentTask Refinement Data Models
struct AgentTaskRefinementResponse: Codable {
    let success: Bool
    let message: String
    let transcription: String?
    let refinementAgentTaskId: String?
    let rootTaskId: String?
    let result: String?
    let refinementIteration: Int?
    let processed: Bool
    
    enum CodingKeys: String, CodingKey {
        case success
        case message
        case transcription
        case refinementAgentTaskId = "refinement_agent_task_id"
        case rootTaskId = "root_task_id"
        case result
        case refinementIteration = "refinement_iteration"
        case processed
    }
}

// MARK: - AgentTask History Data Models

/// Summary item for agentTask history list (sidebar display)
struct AgentTaskListItem: Codable, Identifiable {
    let id: String
    let originalPrompt: String
    let resultPreview: String?
    let timestamp: Date
    let status: String
    let fileCount: Int
    let appName: String?
    let followUpCount: Int  // Number of follow-up agent tasks in the chain
    
    enum CodingKeys: String, CodingKey {
        case id
        case originalPrompt = "original_prompt"
        case resultPreview = "result_preview"
        case timestamp
        case status
        case fileCount = "file_count"
        case appName = "app_name"
        case followUpCount = "follow_up_count"
    }
    
    /// Display title - truncated agent task for sidebar
    var displayTitle: String {
        let truncated = originalPrompt.prefix(40)
        return truncated.count < originalPrompt.count ? "\(truncated)..." : originalPrompt
    }
    
    /// Total agent tasks in chain (1 for single agent task, 1 + followUpCount for chains)
    var chainLength: Int {
        return 1 + followUpCount
    }
}

/// Response for agentTask history list
struct AgentTaskHistoryResponse: Codable {
    let agentTasks: [AgentTaskListItem]
    let totalCount: Int
    let hasMore: Bool
    
    enum CodingKeys: String, CodingKey {
        case agentTasks
        case totalCount = "total_count"
        case hasMore = "has_more"
    }
}

/// An active agent task that is currently processing
struct ActiveAgentItem: Codable, Identifiable {
    let id: String
    let originalPrompt: String
    let timestamp: Date
    let status: String
    let currentStep: String?
    
    enum CodingKeys: String, CodingKey {
        case id
        case originalPrompt = "original_prompt"
        case timestamp
        case status
        case currentStep = "current_step"
    }
    
    /// Display title - truncated agent task for sidebar
    var displayTitle: String {
        let truncated = originalPrompt.prefix(40)
        return truncated.count < originalPrompt.count ? "\(truncated)..." : originalPrompt
    }
}

/// Response for active agents list
struct ActiveAgentsResponse: Codable {
    let agents: [ActiveAgentItem]
    let count: Int
}

/// File reference in agentTask result
struct AgentTaskFileRef: Codable {
    let name: String
    let path: String
    let operation: String?
}

/// A single item in a agentTask chain (parent or follow-up)
struct AgentTaskChainItem: Codable, Identifiable {
    let id: String
    let originalPrompt: String
    let timestamp: Date
    let status: String
    let resultMessage: String?
    let files: [AgentTaskFileRef]
    let rootTaskId: String?
    let previousTaskId: String?
    let chainSequenceNumber: Int
    
    enum CodingKeys: String, CodingKey {
        case id
        case originalPrompt = "original_prompt"
        case timestamp
        case status
        case resultMessage = "result_message"
        case files
        case rootTaskId = "root_task_id"
        case previousTaskId = "previous_task_id"
        case chainSequenceNumber = "chain_sequence_number"
    }
}

/// Full details for a single agentTask including follow-up chain
struct AgentTaskDetail: Codable {
    let id: String
    let originalPrompt: String
    let transcribedPrompt: String
    let timestamp: Date
    let status: String
    let resultMessage: String?  // Extracted from result_data in backend
    let appName: String?
    let windowTitle: String?
    let files: [AgentTaskFileRef]
    let rootTaskId: String?
    let previousTaskId: String?
    let followUps: [AgentTaskChainItem]  // Follow-up agent tasks in the chain
    
    enum CodingKeys: String, CodingKey {
        case id
        case originalPrompt = "original_prompt"
        case transcribedPrompt = "transcribed_prompt"
        case timestamp
        case status
        case resultMessage = "result_message"
        case appName = "app_name"
        case windowTitle = "window_title"
        case files
        case rootTaskId = "root_task_id"
        case previousTaskId = "previous_task_id"
        case followUps = "follow_ups"
    }
}

/// Response for agentTask deletion
struct DeleteAgentTaskResponse: Codable {
    let success: Bool
    let message: String
}

/// Response for checkpoint status check
struct CheckpointStatusResponse: Codable {
    let agentTaskId: String
    let hasCheckpoint: Bool
    let canResume: Bool
    let message: String
    
    enum CodingKeys: String, CodingKey {
        case agentTaskId = "agent_task_id"
        case hasCheckpoint = "has_checkpoint"
        case canResume = "can_resume"
        case message
    }
}

