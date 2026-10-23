import Foundation

// Structured file reference coming from backend result_payload (model-driven)
struct StructuredFileRef: Hashable {
    let name: String
    let fullPath: String
    let operation: String?
}

struct ProgressStep: Hashable {
    let step: String
    let isActive: Bool
    let isComplete: Bool
}

// Workflow plan data structures
struct WorkflowPlan {
    let agentTaskId: String
    let todoCount: Int
    let todos: [TodoItem]
}

struct TodoItem: Identifiable, Hashable {
    let id: String
    let title: String
    let description: String
    var steps: [StepItem]
    var status: TodoStatus = .pending

    enum TodoStatus: String, CaseIterable {
        case pending = "pending"
        case inProgress = "in_progress"
        case completed = "completed"
        case failed = "failed"
    }
}

struct StepItem: Identifiable, Hashable {
    let id: String
    let description: String
    let plannedService: String?
    let plannedMethod: String?
    var status: StepStatus = .pending
    var resultSummary: String?
    var isDynamic: Bool? = false  // Track if this step was added dynamically during agent execution

    enum StepStatus: String, CaseIterable {
        case pending = "pending"
        case inProgress = "in_progress"
        case completed = "completed"
        case failed = "failed"
    }
}
