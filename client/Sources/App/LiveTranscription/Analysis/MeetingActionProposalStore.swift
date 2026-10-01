import Foundation
import Combine

/// Owns all interaction logic for the To-Do Candidates suggested-actions
/// view: local UI state, backend persistence of each proposal's outcome, and
/// live/reopen tracking for legacy proposals that already reference a delegated
/// agent task. New approvals are promoted to durable To-Dos.
///
/// This is deliberately separate from the SwiftUI view so the view stays a thin
/// presentation layer (and both files stay well under the 600-line budget).
///
/// Dismiss/restore persistence is best-effort and optimistic. Promotion waits
/// for the backend to create the To-Do before marking the proposal handled. If
/// `meetingId`/`filename` are unavailable, promotion is a safe no-op and local
/// dismiss/restore behavior remains available.
@MainActor
final class MeetingActionProposalStore: ObservableObject {
    let proposals: [MeetingActionProposal]
    let meetingId: String?
    let filename: String?

    /// Local status overrides keyed by proposal id. When absent, the proposal's
    /// persisted `executionStatus` (from decode) is authoritative.
    @Published var statuses: [String: String] = [:]
    /// In-progress edits to the agent-task prompt, keyed by proposal id.
    @Published var drafts: [String: String] = [:]
    /// Last submit error message, keyed by proposal id.
    @Published var errors: [String: String] = [:]
    /// Proposals whose agent-task prompt is currently being edited.
    @Published var editingIds: Set<String> = []
    /// Delegated agent task id per proposal (seeded from persisted state and
    /// updated on submit). Drives the reopen fetch and the footer label.
    @Published var submittedTaskIds: [String: String] = [:]
    /// Durable To-Do id per promoted proposal (seeded from persisted state and
    /// set on successful promotion). Drives the meeting-analysis To-Do link.
    @Published var todoIds: [String: String] = [:]
    /// Current server-sourced To-Do status. This is transient presentation
    /// state; the To-Do service remains the durable authority.
    @Published var todoStatuses: [String: String] = [:]
    /// Live/terminal status of the delegated agent, keyed by proposal id.
    @Published var liveStatuses: [String: AgentStatus] = [:]

    /// Reverse lookup from delegated agent task id -> proposal id, used to route
    /// websocket events back to the owning proposal.
    private var taskIdToProposalId: [String: String] = [:]
    private var eventCancellable: AnyCancellable?

    init(proposals: [MeetingActionProposal], meetingId: String?, filename: String?) {
        self.proposals = proposals
        self.meetingId = meetingId
        self.filename = filename

        // Seed the delegated-task maps from anything already persisted so a
        // reopened analysis can immediately fetch/stream status for started
        // proposals.
        for proposal in proposals {
            if let taskId = proposal.submittedAgentTaskId, !taskId.isEmpty {
                submittedTaskIds[proposal.id] = taskId
                taskIdToProposalId[taskId] = proposal.id
            }
            if let todoId = proposal.todoId, !todoId.isEmpty {
                todoIds[proposal.id] = todoId
            }
        }

        subscribeToAgentEvents()
    }

    // MARK: - Grouping

    /// Effective status for a proposal: a local override wins over the value
    /// persisted on the model.
    func effectiveStatus(_ proposal: MeetingActionProposal) -> String {
        statuses[proposal.id] ?? proposal.executionStatus
    }

    /// A proposal is "handled" once it has been approved+started (submitted /
    /// completed) or explicitly dismissed. Handled proposals sink to the bottom.
    /// `failed` deliberately stays active so it remains visible for a retry.
    func isHandled(_ status: String) -> Bool {
        switch status {
        case "submitted", "completed", "dismissed", "added_to_todos":
            return true
        default:
            return false
        }
    }

    var activeProposals: [MeetingActionProposal] {
        proposals.filter { !isHandled(effectiveStatus($0)) }
    }

    var handledProposals: [MeetingActionProposal] {
        proposals.filter { isHandled(effectiveStatus($0)) }
    }

    // MARK: - Editing

    func canSubmit(_ proposal: MeetingActionProposal) -> Bool {
        let status = effectiveStatus(proposal)
        let prompt = currentPrompt(proposal).trimmingCharacters(in: .whitespacesAndNewlines)
        return !prompt.isEmpty && todoIds[proposal.id] == nil && (status == "proposed" || status == "failed")
    }

    func canStart(_ proposal: MeetingActionProposal) -> Bool {
        let status = effectiveStatus(proposal)
        let prompt = currentPrompt(proposal).trimmingCharacters(in: .whitespacesAndNewlines)
        return !prompt.isEmpty && (status == "proposed" || status == "failed")
    }

    func isEligibleForBulkPromotion(_ proposal: MeetingActionProposal) -> Bool {
        canSubmit(proposal)
    }

    func currentPrompt(_ proposal: MeetingActionProposal) -> String {
        drafts[proposal.id] ?? proposal.suggestedAgentTask
    }

    func isEditing(_ proposal: MeetingActionProposal) -> Bool {
        editingIds.contains(proposal.id)
    }

    func toggleEditing(_ proposal: MeetingActionProposal) {
        if editingIds.contains(proposal.id) {
            editingIds.remove(proposal.id)
        } else {
            drafts[proposal.id] = drafts[proposal.id] ?? proposal.suggestedAgentTask
            editingIds.insert(proposal.id)
        }
    }

    // MARK: - Outcome actions

    private enum ProposalAction {
        case addToTodos
        case startNow
    }

    private enum ProposalActionError: LocalizedError {
        case unactionableTodoStatus(String)

        var errorDescription: String? {
            switch self {
            case .unactionableTodoStatus(let status):
                return "This To-Do cannot be started because it is \(status)."
            }
        }
    }

    func submit(_ proposal: MeetingActionProposal) async {
        await performProposalAction(proposal, action: .addToTodos, setPendingState: true)
    }

    func startNow(_ proposal: MeetingActionProposal) async {
        guard canStart(proposal) else { return }
        await performProposalAction(proposal, action: .startNow, setPendingState: true)
    }

    func submitAllEligible() async {
        guard meetingId != nil, filename != nil else { return }
        let eligible = proposals.filter(isEligibleForBulkPromotion)
        for proposal in eligible {
            statuses[proposal.id] = "submitting"
            errors[proposal.id] = nil
        }
        for proposal in eligible {
            await performProposalAction(proposal, action: .addToTodos, setPendingState: false)
        }
    }

    private func performProposalAction(
        _ proposal: MeetingActionProposal,
        action: ProposalAction,
        setPendingState: Bool
    ) async {
        guard let meetingId = self.meetingId, let filename = self.filename else { return }
        if setPendingState {
            statuses[proposal.id] = action == .startNow ? "starting" : "submitting"
            errors[proposal.id] = nil
        }

        do {
            let suggestedAgentTask = currentPrompt(proposal).trimmingCharacters(in: .whitespacesAndNewlines)
            let response = try await APIClient.shared.promoteMeetingProposalToTodo(
                meetingId: meetingId,
                filename: filename,
                proposal: proposal,
                suggestedAgentTask: suggestedAgentTask
            )
            todoIds[proposal.id] = response.id
            todoStatuses[proposal.id] = response.status

            switch action {
            case .addToTodos:
                statuses[proposal.id] = "added_to_todos"
                if let staleTaskId = submittedTaskIds.removeValue(forKey: proposal.id) {
                    taskIdToProposalId.removeValue(forKey: staleTaskId)
                }
                liveStatuses.removeValue(forKey: proposal.id)
                persist(proposal, status: "added_to_todos", agentTaskId: nil, todoId: response.id)
            case .startNow:
                let launched = try await launchWorkerIfNeeded(response)
                applyWorkerAttempt(
                    from: launched.item,
                    agentTaskId: launched.agentTaskId,
                    proposalId: proposal.id
                )
                todoStatuses[proposal.id] = launched.item.status
                let persistedStatus = persistedStartStatus(for: launched.item)
                statuses[proposal.id] = persistedStatus
                persist(
                    proposal,
                    status: persistedStatus,
                    agentTaskId: submittedTaskIds[proposal.id],
                    todoId: response.id
                )
            }
        } catch {
            statuses[proposal.id] = "failed"
            errors[proposal.id] = error.localizedDescription
            persist(proposal, status: "failed", agentTaskId: submittedTaskIds[proposal.id], todoId: todoIds[proposal.id])
        }
    }

    private func launchWorkerIfNeeded(_ promoted: TodoItemDetailResponse) async throws -> TodoWorkerLaunchResponse {
        switch promoted.status {
        case "open":
            return try await APIClient.shared.launchTodoWorker(todoId: promoted.id, expectedRevision: promoted.revision)
        case "in_progress", "ready_for_review", "completed":
            guard let attempt = promoted.workerAttempts.last else {
                throw ProposalActionError.unactionableTodoStatus(promoted.status)
            }
            return TodoWorkerLaunchResponse(item: promoted, agentTaskId: attempt.agentTaskId)
        case "candidate", "dismissed", "canceled":
            throw ProposalActionError.unactionableTodoStatus(promoted.status)
        default:
            throw ProposalActionError.unactionableTodoStatus(promoted.status)
        }
    }

    private func applyWorkerAttempt(
        from detail: TodoItemDetailResponse,
        agentTaskId: String,
        proposalId: String
    ) {
        let workerStatus = detail.workerAttempts.first(where: { $0.agentTaskId == agentTaskId })?.status ?? "processing"
        if let staleTaskId = submittedTaskIds[proposalId], staleTaskId != agentTaskId {
            taskIdToProposalId.removeValue(forKey: staleTaskId)
        }
        submittedTaskIds[proposalId] = agentTaskId
        taskIdToProposalId[agentTaskId] = proposalId
        liveStatuses[proposalId] = mappedLiveStatus(workerStatus)
    }

    private func mappedLiveStatus(_ workerStatus: String) -> AgentStatus {
        switch workerStatus {
        case "capturing":
            return .capturing
        case "routing":
            return .routing
        case "processing", "awaiting_provider_delegation", "awaiting_delegated_agents", "paused":
            return .processing
        case "awaiting_user_input", "needs_clarification":
            return .awaitingInput
        case "completed":
            return .completed
        default:
            return .failed
        }
    }

    private func persistedStartStatus(for detail: TodoItemDetailResponse) -> String {
        if detail.status == "completed" {
            return "completed"
        }
        if let attempt = detail.workerAttempts.last, attempt.status == "completed" {
            return "completed"
        }
        return "submitted"
    }

    func dismiss(_ proposal: MeetingActionProposal) {
        statuses[proposal.id] = "dismissed"
        editingIds.remove(proposal.id)
        persist(proposal, status: "dismissed", agentTaskId: nil)
    }

    func restore(_ proposal: MeetingActionProposal) {
        // Return the card to its actionable state. We set an explicit "proposed"
        // override (rather than dropping to the decoded value) so restore also
        // works for proposals that were decoded as dismissed/submitted.
        statuses[proposal.id] = "proposed"
        submittedTaskIds.removeValue(forKey: proposal.id)
        liveStatuses.removeValue(forKey: proposal.id)
        persist(proposal, status: "proposed", agentTaskId: nil)
    }

    // MARK: - Persistence

    /// Persist a proposal outcome to its analysis file. No-ops (AC5) when the
    /// meeting id or filename is unavailable. Failures are logged, never fatal.
    private func persist(_ proposal: MeetingActionProposal, status: String, agentTaskId: String?, todoId: String? = nil) {
        guard let meetingId = meetingId, let filename = filename else {
            #if DEBUG
            DevLogger.shared.info("↩️ Skipping proposal persistence (no meetingId/filename) for \(proposal.id)", context: "ProposalStore")
            #endif
            return
        }

        Task {
            do {
                try await APIClient.shared.updateMeetingAnalysisProposal(
                    meetingId: meetingId,
                    filename: filename,
                    proposalId: proposal.id,
                    executionStatus: status,
                    submittedAgentTaskId: agentTaskId,
                    todoId: todoId
                )
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Failed to persist proposal \(proposal.id): \(error)", context: "ProposalStore")
                #endif
            }
        }
    }

    // MARK: - Linked-work refresh

    /// On analysis open, retrieve the current state of every durable linked
    /// record. Each request is isolated so a missing task or To-Do does not
    /// suppress the remaining links or status rows.
    func refreshLinkedWorkStatuses() async {
        for proposal in proposals {
            if let todoId = todoIds[proposal.id], !todoId.isEmpty {
                await refreshTodoStatus(for: proposal.id, todoId: todoId)
            }
            if let taskId = submittedTaskIds[proposal.id], !taskId.isEmpty,
               liveStatuses[proposal.id] == nil {
                await refreshDelegatedStatus(for: proposal.id, taskId: taskId)
            }
        }
    }

    private func refreshTodoStatus(for proposalId: String, todoId: String) async {
        do {
            todoStatuses[proposalId] = try await APIClient.shared.getTodoItemDetail(todoId: todoId).status
        } catch {
            #if DEBUG
            DevLogger.shared.info("ℹ️ No To-Do status for proposal \(proposalId) (To-Do \(todoId)): \(error)", context: "ProposalStore")
            #endif
        }
    }

    private func refreshDelegatedStatus(for proposalId: String, taskId: String) async {
        do {
            let detail = try await APIClient.shared.getAgentTask(agentTaskId: taskId)
            if let status = AgentStatus(rawValue: detail.status) {
                liveStatuses[proposalId] = status
            }
        } catch {
            #if DEBUG
            DevLogger.shared.info("ℹ️ No delegated status for proposal \(proposalId) (task \(taskId)): \(error)", context: "ProposalStore")
            #endif
        }
    }

    // MARK: - Live streaming

    /// Subscribe to the shared websocket stream, mapping agent events back to the
    /// owning proposal by `agent_task_id`. Scoped to our proposals only; we do
    /// not register into AgentManager so its active-agent widget is unaffected.
    private func subscribeToAgentEvents() {
        eventCancellable = WebSocketService.shared.eventSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleAgentEvent(event)
            }
    }

    private func handleAgentEvent(_ event: WebSocketEvent) {
        switch event {
        case .agentTaskProgress(let data):
            guard let proposalId = proposalId(for: data) else { return }
            if let statusStr = data["status"] as? String, statusStr == "started" {
                liveStatuses[proposalId] = .processing
            }

        case .agentTaskResult(let data):
            guard let proposalId = proposalId(for: data) else { return }
            let success = (data["success"] as? Bool) ?? false
            let needsClarification = (data["requires_clarification"] as? Bool) == true ||
                                     (data["needs_clarification"] as? Bool) == true
            if needsClarification {
                liveStatuses[proposalId] = .awaitingInput
            } else if success {
                liveStatuses[proposalId] = .completed
            } else {
                liveStatuses[proposalId] = .failed
            }
            if let todoId = todoIds[proposalId], !todoId.isEmpty {
                Task { [weak self] in
                    await self?.refreshTodoStatus(for: proposalId, todoId: todoId)
                }
            }

        case .checkpointWaiting(let data):
            guard let proposalId = proposalId(for: data) else { return }
            liveStatuses[proposalId] = .awaitingInput

        case .checkpointResumed(let data):
            guard let proposalId = proposalId(for: data) else { return }
            liveStatuses[proposalId] = .processing

        default:
            break
        }
    }

    private func proposalId(for data: [String: Any]) -> String? {
        guard let taskId = data["agent_task_id"] as? String else { return nil }
        return taskIdToProposalId[taskId]
    }
}
