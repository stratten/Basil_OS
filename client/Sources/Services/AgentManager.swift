import Foundation
import Combine
import SwiftUI

/// Represents the current status of an active agent
enum AgentStatus: String, CaseIterable {
    case capturing = "capturing"  // Recording voice input
    case routing = "routing"
    case processing = "processing"
    case awaitingInput = "awaiting_user_input"
    case completed = "completed"
    case failed = "failed"
    
    var isActive: Bool {
        switch self {
        case .capturing, .routing, .processing, .awaitingInput:
            return true
        case .completed, .failed:
            return false
        }
    }
    
    var displayName: String {
        switch self {
        case .capturing: return "Recording..."
        case .routing: return "Starting..."
        case .processing: return "Processing"
        case .awaitingInput: return "Waiting for input"
        case .completed: return "Completed"
        case .failed: return "Failed"
        }
    }
}

/// Represents an active agent being tracked by the AgentManager
struct ActiveAgent: Identifiable, Equatable {
    let id: String  // agent_task_id
    var originalPrompt: String
    var status: AgentStatus
    var currentStep: String?
    var hasUnreadResult: Bool = false
    var createdAt: Date = Date()
    
    // Result storage for multi-agent support
    var result: String?
    var isError: Bool = false
    
    /// Weak reference to the ViewModel is not stored here to avoid Equatable issues
    /// Instead, viewModels are tracked separately in AgentManager
    
    static func == (lhs: ActiveAgent, rhs: ActiveAgent) -> Bool {
        lhs.id == rhs.id &&
        lhs.originalPrompt == rhs.originalPrompt &&
        lhs.status == rhs.status &&
        lhs.currentStep == rhs.currentStep &&
        lhs.hasUnreadResult == rhs.hasUnreadResult &&
        lhs.result == rhs.result &&
        lhs.isError == rhs.isError
    }
}

/// Central manager for tracking all active agentTask agents
/// Handles WebSocket event routing to correct ViewModels
@MainActor
final class AgentManager: ObservableObject {
    
    // MARK: - Singleton
    
    static let shared = AgentManager()
    
    // MARK: - Published Properties
    
    /// All currently active agents (processing, awaiting input, or recently completed)
    @Published private(set) var activeAgents: [ActiveAgent] = []
    
    /// ID of the currently focused agent (shown in main widget area)
    @Published var focusedAgentId: String?
    
    // MARK: - Private Properties
    
    /// ViewModels indexed by agent_task_id for event routing
    private var viewModels: [String: WeakViewModel] = [:]
    
    /// WebSocket subscription
    private var cancellables = Set<AnyCancellable>()
    
    /// Wrapper to hold weak reference to an associated runtime object.
    /// We intentionally keep this untyped to avoid hard coupling to legacy
    /// AgentTaskResultViewModel implementations.
    private struct WeakViewModel {
        weak var viewModel: AnyObject?
    }
    
    // MARK: - Initialization
    
    private init() {
        setupWebSocketSubscription()
        setupPeriodicCleanup()
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Initialized", context: "AgentManager")
        #endif
    }
    
    /// Set up periodic cleanup of stale agents
    private func setupPeriodicCleanup() {
        // Clean up stale agents every 30 seconds
        Timer.publish(every: 30, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.cleanupStaleAgents()
            }
            .store(in: &cancellables)
    }
    
    // MARK: - Public Methods
    
    /// Register a new agent with its ViewModel
    /// - Parameters:
    ///   - agentTaskId: The AgentTask ID for this agent
    ///   - originalPrompt: The original agentTask text
    ///   - viewModel: The ViewModel handling this agent
    ///   - initialStatus: The initial status (default: .routing)
    func registerAgent(agentTaskId: String, originalPrompt: String, viewModel: AnyObject, initialStatus: AgentStatus = .routing) {
        // Create or update agent entry
        if let existingIndex = activeAgents.firstIndex(where: { $0.id == agentTaskId }) {
            // Update originalPrompt (may have been placeholder)
            if !originalPrompt.isEmpty && originalPrompt != "Recording..." {
                activeAgents[existingIndex].originalPrompt = originalPrompt
            }
            // Don't overwrite .capturing status - preserve it until capture completes
            // This allows registerCapturingAgent to be called first, then registerAgent later
            if activeAgents[existingIndex].status != .capturing {
                activeAgents[existingIndex].status = initialStatus
            }
        } else {
            let agent = ActiveAgent(
                id: agentTaskId,
                originalPrompt: originalPrompt,
                status: initialStatus,
                currentStep: nil
            )
            activeAgents.append(agent)
        }
        
        // Store ViewModel reference
        viewModels[agentTaskId] = WeakViewModel(viewModel: viewModel)
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Registered agent: \(agentTaskId) - '\(originalPrompt.prefix(30))...' (status: \(activeAgents.first(where: { $0.id == agentTaskId })?.status.rawValue ?? "unknown"))", context: "AgentManager")
        #endif
        
        // Notify observers
        objectWillChange.send()
    }
    
    /// Register a capturing agent before ViewModel is available
    /// Used when starting a new AgentTask while result widget is visible
    /// - Parameters:
    ///   - agentTaskId: The pre-generated AgentTask ID
    ///   - placeholder: Placeholder text while recording (e.g., "Recording...")
    func registerCapturingAgent(agentTaskId: String, placeholder: String = "Recording...") {
        // Only add if not already registered
        guard !activeAgents.contains(where: { $0.id == agentTaskId }) else { return }
        
        let agent = ActiveAgent(
            id: agentTaskId,
            originalPrompt: placeholder,
            status: .capturing,
            currentStep: nil
        )
        activeAgents.append(agent)
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Registered capturing agent: \(agentTaskId)", context: "AgentManager")
        #endif
        
        objectWillChange.send()
    }
    
    /// Associate a ViewModel with an existing capturing agent
    /// Called when the ViewModel is created after capture starts
    func associateViewModel(agentTaskId: String, viewModel: AnyObject) {
        viewModels[agentTaskId] = WeakViewModel(viewModel: viewModel)
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Associated ViewModel with agent: \(agentTaskId)", context: "AgentManager")
        #endif
    }
    
    /// Unregister an agent when it's dismissed
    /// - Parameter agentTaskId: The AgentTask ID to remove
    func unregisterAgent(agentTaskId: String) {
        activeAgents.removeAll { $0.id == agentTaskId }
        viewModels.removeValue(forKey: agentTaskId)
        
        // If this was the focused agent, clear focus
        if focusedAgentId == agentTaskId {
            focusedAgentId = nil
        }
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Unregistered agent: \(agentTaskId)", context: "AgentManager")
        #endif
        
        objectWillChange.send()
    }
    
    /// Update an agent's status
    /// - Parameters:
    ///   - agentTaskId: The AgentTask ID to update
    ///   - status: The new status
    func updateAgentStatus(agentTaskId: String, status: AgentStatus) {
        guard let index = activeAgents.firstIndex(where: { $0.id == agentTaskId }) else { return }
        
        let previousStatus = activeAgents[index].status
        activeAgents[index].status = status
        
        // Mark as unread if completed while not focused
        if status == .completed && focusedAgentId != agentTaskId {
            activeAgents[index].hasUnreadResult = true
        }
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Agent \(agentTaskId) status: \(previousStatus.rawValue) -> \(status.rawValue)", context: "AgentManager")
        #endif
        
        objectWillChange.send()
        
        // Don't auto-remove completed agents - they stay visible with unread badge
        // until user clicks on them to view the result
    }
    
    /// Update an agent's current step
    /// - Parameters:
    ///   - agentTaskId: The AgentTask ID to update
    ///   - step: The current step description
    func updateAgentStep(agentTaskId: String, step: String?) {
        guard let index = activeAgents.firstIndex(where: { $0.id == agentTaskId }) else { return }
        
        activeAgents[index].currentStep = step
        objectWillChange.send()
    }
    
    /// Store an agent's result (for multi-agent support, allows retrieval when switching focus)
    /// - Parameters:
    ///   - agentTaskId: The AgentTask ID to update
    ///   - result: The result text
    ///   - isError: Whether this is an error result
    func storeAgentResult(agentTaskId: String, result: String, isError: Bool) {
        guard let index = activeAgents.firstIndex(where: { $0.id == agentTaskId }) else { return }
        
        activeAgents[index].result = result
        activeAgents[index].isError = isError
        objectWillChange.send()
    }
    
    /// Update an agent's agent task text (e.g., when transcription completes)
    /// - Parameters:
    ///   - agentTaskId: The AgentTask ID to update
    ///   - agentTaskText: The updated agent task text
    func updateAgentTaskText(agentTaskId: String, agentTaskText: String) {
        guard let index = activeAgents.firstIndex(where: { $0.id == agentTaskId }) else { return }
        
        activeAgents[index].originalPrompt = agentTaskText
        objectWillChange.send()
    }
    
    /// Mark an agent as read (when focused)
    /// - Parameter agentTaskId: The AgentTask ID to mark as read
    func markAgentAsRead(agentTaskId: String) {
        guard let index = activeAgents.firstIndex(where: { $0.id == agentTaskId }) else { return }
        
        if activeAgents[index].hasUnreadResult {
            activeAgents[index].hasUnreadResult = false
            objectWillChange.send()
        }
    }
    
    /// Set the focused agent and mark it as read
    /// - Parameter agentTaskId: The AgentTask ID to focus
    func focusAgent(agentTaskId: String) {
        focusedAgentId = agentTaskId
        markAgentAsRead(agentTaskId: agentTaskId)
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] Focused agent: \(agentTaskId)", context: "AgentManager")
        #endif
    }
    
    /// Get the ViewModel for a specific AgentTask
    /// - Parameter agentTaskId: The AgentTask ID
    /// - Returns: The ViewModel if it exists and is still valid
    func getViewModel(for agentTaskId: String) -> AnyObject? {
        return viewModels[agentTaskId]?.viewModel
    }
    
    /// Get the currently focused ViewModel
    /// - Returns: The focused ViewModel if one exists
    func getFocusedViewModel() -> AnyObject? {
        guard let focusedId = focusedAgentId else { return nil }
        return getViewModel(for: focusedId)
    }
    
    /// Get all active (non-completed) agents
    var runningAgents: [ActiveAgent] {
        activeAgents.filter { $0.status.isActive }
    }
    
    /// Get count of agents with unread results
    var unreadCount: Int {
        activeAgents.filter { $0.hasUnreadResult }.count
    }
    
    /// Check if there are any actively processing agents
    var hasActiveAgents: Bool {
        !runningAgents.isEmpty
    }
    
    // MARK: - WebSocket Event Routing
    
    private func setupWebSocketSubscription() {
        WebSocketService.shared.eventSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.routeWebSocketEvent(event)
            }
            .store(in: &cancellables)
        
        #if DEBUG
        DevLogger.shared.info("[AgentManager] WebSocket subscription established", context: "AgentManager")
        #endif
    }
    
    private func routeWebSocketEvent(_ event: WebSocketEvent) {
        // Extract agent_task_id from event data if present
        switch event {
        case .agentTaskProgress(let data),
             .agentTaskResult(let data),
             .workflowPlanReady(let data),
             .stepProgressUpdate(let data),
             .dynamicStepAdded(let data),
             .dynamicStepUpdated(let data),
             .agentProgressUpdate(let data),
             .collaborativeCheckpointRequest(let data),
             .checkpointWaiting(let data),
             .checkpointResumed(let data),
             .sessionContextInfo(let data),
             .executionApprovalRequest(let data):
            
            // Try to extract agent_task_id
            if let agentTaskId = data["agent_task_id"] as? String {
                // Update agent state based on event type
                updateAgentFromEvent(event, agentTaskId: agentTaskId, data: data)
            }
            
        default:
            // Events without agent_task_id - handled normally by ViewModels
            break
        }
    }
    
    private func updateAgentFromEvent(_ event: WebSocketEvent, agentTaskId: String, data: [String: Any]) {
        switch event {
        case .agentTaskProgress:
            // Update current step if provided
            if let step = data["step"] as? String {
                updateAgentStep(agentTaskId: agentTaskId, step: step)
            }
            // Update status if provided
            if let statusStr = data["status"] as? String {
                if statusStr == "started" {
                    updateAgentStatus(agentTaskId: agentTaskId, status: .processing)
                }
            }
            // Update agent task text if this is the first progress with details
            if let details = data["details"] as? String,
               let step = data["step"] as? String,
               step == "Analyzing request" {
                updateAgentTaskText(agentTaskId: agentTaskId, agentTaskText: details)
            }
            
        case .agentTaskResult(let resultData):
            // Determine final status
            let success = resultData["success"] as? Bool ?? false
            let needsClarification = (resultData["requires_clarification"] as? Bool) == true ||
                                    (resultData["needs_clarification"] as? Bool) == true
            
            if needsClarification {
                updateAgentStatus(agentTaskId: agentTaskId, status: .awaitingInput)
            } else if success {
                updateAgentStatus(agentTaskId: agentTaskId, status: .completed)
                updateAgentStep(agentTaskId: agentTaskId, step: nil)
            } else {
                updateAgentStatus(agentTaskId: agentTaskId, status: .failed)
                updateAgentStep(agentTaskId: agentTaskId, step: nil)
            }
            
        case .checkpointWaiting:
            updateAgentStatus(agentTaskId: agentTaskId, status: .awaitingInput)
            if let prompt = (data["checkpoint_data"] as? [String: Any])?["prompt"] as? String {
                updateAgentStep(agentTaskId: agentTaskId, step: prompt)
            }
            
        case .checkpointResumed:
            updateAgentStatus(agentTaskId: agentTaskId, status: .processing)
            
        case .agentProgressUpdate:
            if let message = data["message"] as? String {
                updateAgentStep(agentTaskId: agentTaskId, step: message)
            }
            
        default:
            break
        }
    }
    
    // MARK: - Cleanup
    
    /// Clean up any stale agent references (ViewModels that have been deallocated)
    func cleanupStaleAgents() {
        var staleIds: [String] = []
        
        for (agentTaskId, weakVM) in viewModels {
            if weakVM.viewModel == nil {
                staleIds.append(agentTaskId)
            }
        }
        
        for agentTaskId in staleIds {
            unregisterAgent(agentTaskId: agentTaskId)
        }
        
        if !staleIds.isEmpty {
            #if DEBUG
            DevLogger.shared.info("[AgentManager] Cleaned up \(staleIds.count) stale agents", context: "AgentManager")
            #endif
        }
    }
}
