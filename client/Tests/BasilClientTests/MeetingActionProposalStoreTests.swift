import XCTest
@testable import BasilClient

/// Intercepts every `URLSession.shared` request process-wide for the
/// duration of a test. Route by path suffix so the promotion endpoint and
/// the legacy proposal-update endpoint (fired best-effort inside `persist`)
/// can be stubbed independently within the same test.
final class TodoFixtureURLProtocol: URLProtocol {
    struct StubbedResponse {
        let statusCode: Int
        let body: Data
    }

    /// Path-suffix -> canned response. Cleared and repopulated per test.
    static var stubs: [String: StubbedResponse] = [:]
    /// Sequential promote responses, consumed FIFO before `stubs`.
    static var promoteQueue: [StubbedResponse] = []
    /// Every intercepted request, in order, for call-count/body assertions.
    static var capturedRequests: [URLRequest] = []
    /// Request bodies keyed by the same order as `capturedRequests`, because
    /// `URLSession` often moves `httpBody` onto `httpBodyStream`.
    static var capturedBodies: [Data] = []

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        TodoFixtureURLProtocol.capturedRequests.append(request)
        if let body = request.httpBody {
            TodoFixtureURLProtocol.capturedBodies.append(body)
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var collected = Data()
            let bufferSize = 1024
            var buffer = [UInt8](repeating: 0, count: bufferSize)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: bufferSize)
                if read > 0 {
                    collected.append(buffer, count: read)
                } else {
                    break
                }
            }
            TodoFixtureURLProtocol.capturedBodies.append(collected)
        } else {
            TodoFixtureURLProtocol.capturedBodies.append(Data())
        }
        guard let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        let matchedStub: StubbedResponse?
        if url.path.hasSuffix("/api/v1/todos/meeting-proposals/promote"), !TodoFixtureURLProtocol.promoteQueue.isEmpty {
            matchedStub = TodoFixtureURLProtocol.promoteQueue.removeFirst()
        } else if let exact = TodoFixtureURLProtocol.stubs.first(where: { url.path.hasSuffix($0.key) })?.value {
            matchedStub = exact
        } else if url.path.contains("/proposals/") {
            matchedStub = .init(statusCode: 200, body: Data("{}".utf8))
        } else {
            matchedStub = nil
        }
        guard let stub = matchedStub else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        let response = HTTPURLResponse(url: url, statusCode: stub.statusCode, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: stub.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

@MainActor
final class MeetingActionProposalStoreTests: XCTestCase {
    override class func setUp() {
        super.setUp()
        URLProtocol.registerClass(TodoFixtureURLProtocol.self)
    }

    override class func tearDown() {
        URLProtocol.unregisterClass(TodoFixtureURLProtocol.self)
        super.tearDown()
    }

    override func setUp() {
        super.setUp()
        TodoFixtureURLProtocol.stubs = [:]
        TodoFixtureURLProtocol.promoteQueue = []
        TodoFixtureURLProtocol.capturedRequests = []
        TodoFixtureURLProtocol.capturedBodies = []
        APIClient.shared.isBackendAvailable = true
    }

    private func makeProposal(
        id: String = "proposal-1",
        executionStatus: String = "proposed",
        submittedAgentTaskId: String? = nil,
        todoId: String? = nil,
        executionMode: String? = "agent_assisted"
    ) -> MeetingActionProposal {
        MeetingActionProposal(
            id: id,
            sourceActionItemIndex: 0,
            sourceTask: "Follow up with Alex about the launch checklist.",
            sourceContext: "Alex asked about the timeline.",
            sourceTimestamp: 12.5,
            sourceSpeaker: "Alex",
            suggestedAgentTask: "Draft a follow-up email to Alex about the launch checklist.",
            capabilityType: "email_draft",
            confidence: 0.9,
            whyBasilCanHelp: "Basil can draft the follow-up from meeting context.",
            missingInformation: [],
            requiresUserConfirmation: false,
            executionMode: executionMode,
            workspaceSource: "meeting-1",
            executionStatus: executionStatus,
            submittedAgentTaskId: submittedAgentTaskId,
            todoId: todoId
        )
    }

    private func promotionBody(todoId: String, status: String, revision: Int = 1) -> Data {
        Data(#"{"id":"\#(todoId)","status":"\#(status)","revision":\#(revision),"worker_attempts":[]}"#.utf8)
    }

    private func stubPromotionSuccess(todoId: String = "todo-abc123", status: String = "open") {
        TodoFixtureURLProtocol.stubs["/api/v1/todos/meeting-proposals/promote"] = .init(
            statusCode: 200, body: promotionBody(todoId: todoId, status: status)
        )
    }

    private func stubWorkerLaunchSuccess(todoId: String = "todo-abc123") {
        let body = Data(#"{"item":{"id":"\#(todoId)","status":"in_progress","revision":2,"worker_attempts":[{"agent_task_id":"worker-old","status":"completed"},{"agent_task_id":"worker-returned","status":"processing"}]},"agent_task_id":"worker-returned"}"#.utf8)
        TodoFixtureURLProtocol.stubs["/api/v1/todos/items/\(todoId)/workers"] = .init(statusCode: 200, body: body)
    }

    private func stubWorkerLaunchFailure(todoId: String = "todo-abc123", statusCode: Int = 500) {
        TodoFixtureURLProtocol.stubs["/api/v1/todos/items/\(todoId)/workers"] = .init(
            statusCode: statusCode, body: Data(#"{"detail":"worker launch failed"}"#.utf8)
        )
    }

    private func capturedRequests(pathSuffix: String) -> [URLRequest] {
        TodoFixtureURLProtocol.capturedRequests.filter { $0.url?.path.hasSuffix(pathSuffix) == true }
    }

    private func capturedBodies(pathSuffix: String) -> [Data] {
        zip(TodoFixtureURLProtocol.capturedRequests, TodoFixtureURLProtocol.capturedBodies)
            .filter { $0.0.url?.path.hasSuffix(pathSuffix) == true }
            .map(\.1)
    }

    private func stubPromotionFailure(statusCode: Int = 500) {
        TodoFixtureURLProtocol.stubs["/api/v1/todos/meeting-proposals/promote"] = .init(
            statusCode: statusCode, body: "{\"detail\":\"promotion failed\"}".data(using: .utf8)!
        )
    }

    private func stubProposalUpdateSuccess() {
        TodoFixtureURLProtocol.stubs["/analyses/analysis_20260101_000000.json/proposals/proposal-1"] = .init(
            statusCode: 200, body: "{}".data(using: .utf8)!
        )
    }

    // MARK: - submit() promotion flow

    func test_submit_onSuccess_setsAddedToTodosStatusAndStoresTodoId() async {
        stubPromotionSuccess(todoId: "todo-xyz")
        stubProposalUpdateSuccess()
        let proposal = makeProposal(submittedAgentTaskId: "legacy-agent-task")
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )
        store.liveStatuses[proposal.id] = .processing

        await store.submit(proposal)

        XCTAssertEqual(store.statuses[proposal.id], "added_to_todos")
        XCTAssertEqual(store.todoIds[proposal.id], "todo-xyz")
        XCTAssertNil(store.submittedTaskIds[proposal.id])
        XCTAssertNil(store.liveStatuses[proposal.id])
        XCTAssertNil(store.errors[proposal.id])
    }

    func test_submit_onSuccess_promotedProposalBecomesHandledAndNoLongerSubmittable() async {
        stubPromotionSuccess()
        stubProposalUpdateSuccess()
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.submit(proposal)

        XCTAssertTrue(store.isHandled(store.effectiveStatus(proposal)))
        XCTAssertTrue(store.handledProposals.contains { $0.id == proposal.id })
        XCTAssertFalse(store.activeProposals.contains { $0.id == proposal.id })
        XCTAssertFalse(store.canSubmit(proposal))
    }

    func test_submit_onServerError_setsFailedStatusAndDoesNotStoreATodoId() async {
        stubPromotionFailure(statusCode: 500)
        stubProposalUpdateSuccess()
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.submit(proposal)

        XCTAssertEqual(store.statuses[proposal.id], "failed")
        XCTAssertNil(store.todoIds[proposal.id])
        XCTAssertNotNil(store.errors[proposal.id])
        XCTAssertFalse(store.isHandled(store.effectiveStatus(proposal))) // failed stays active for a retry
        XCTAssertTrue(store.canSubmit(proposal))
    }

    func test_submit_withoutMeetingIdOrFilename_isANoOpAndLeavesStatusUnset() async {
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(proposals: [proposal], meetingId: nil, filename: nil)

        await store.submit(proposal)

        XCTAssertNil(store.statuses[proposal.id])
        XCTAssertTrue(TodoFixtureURLProtocol.capturedRequests.isEmpty)
    }

    func test_submit_onlyChangesThePromotedProposalsCardWhenMultiplePresent() async {
        stubPromotionSuccess(todoId: "todo-a")
        stubProposalUpdateSuccess()
        let target = makeProposal(id: "proposal-1")
        let other = makeProposal(id: "proposal-2")
        let store = MeetingActionProposalStore(
            proposals: [target, other], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.submit(target)

        XCTAssertEqual(store.statuses[target.id], "added_to_todos")
        XCTAssertNil(store.statuses[other.id]) // untouched; falls back to its persisted "proposed" default
        XCTAssertEqual(store.effectiveStatus(other), "proposed")
    }

    func testRefreshLinkedWorkStatusesLoadsCurrentTodoOutcome() async {
        TodoFixtureURLProtocol.stubs["/api/v1/todos/items/todo-seeded"] = .init(
            statusCode: 200,
            body: promotionBody(todoId: "todo-seeded", status: "ready_for_review", revision: 4)
        )
        let proposal = makeProposal(executionStatus: "added_to_todos", todoId: "todo-seeded")
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.refreshLinkedWorkStatuses()

        XCTAssertEqual(store.todoStatuses[proposal.id], "ready_for_review")
        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/items/todo-seeded").count, 1)
    }

    // MARK: - Legacy decode compatibility

    func test_legacyProposalJSONWithoutTodoId_decodesWithNilTodoIdAndDoesNotCrash() throws {
        let legacyJSON = """
        {
            "id": "legacy-1",
            "source_action_item_index": 0,
            "source_task": "Old proposal from before this change",
            "source_context": null,
            "source_timestamp": 1.0,
            "source_speaker": null,
            "suggested_agent_task": "Do the old thing",
            "capability_type": "email_draft",
            "confidence": 0.8,
            "why_basil_can_help": "because",
            "missing_information": [],
            "requires_user_confirmation": false,
            "workspace_source": "meeting-old",
            "execution_status": "submitted",
            "submitted_agent_task_id": "old-task-1"
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(MeetingActionProposal.self, from: legacyJSON)

        XCTAssertNil(decoded.todoId)
        XCTAssertNil(decoded.executionMode)
        XCTAssertEqual(decoded.executionStatus, "submitted")
        let store = MeetingActionProposalStore(proposals: [decoded], meetingId: "meeting-old", filename: "f.json")
        XCTAssertEqual(store.submittedTaskIds[decoded.id], "old-task-1")
        XCTAssertNil(store.todoIds[decoded.id])
        XCTAssertTrue(store.isHandled(store.effectiveStatus(decoded))) // legacy "submitted" still sinks to handled
    }

    func testDismissAndRestoreRoundTripEffectiveStatus() {
        let proposal = MeetingActionProposal(
            id: "p1",
            sourceActionItemIndex: nil,
            sourceTask: "Follow up with vendor",
            sourceContext: nil,
            sourceTimestamp: nil,
            sourceSpeaker: nil,
            suggestedAgentTask: "Draft a follow-up email",
            capabilityType: "email",
            confidence: 0.9,
            whyBasilCanHelp: "Basil can draft this",
            missingInformation: [],
            requiresUserConfirmation: true,
            workspaceSource: "meeting",
            executionStatus: "proposed",
            submittedAgentTaskId: nil,
            todoId: nil
        )
        let store = MeetingActionProposalStore(proposals: [proposal], meetingId: nil, filename: nil)

        XCTAssertEqual(store.effectiveStatus(proposal), "proposed")
        store.dismiss(proposal)
        XCTAssertEqual(store.effectiveStatus(proposal), "dismissed")
        store.restore(proposal)
        XCTAssertEqual(store.effectiveStatus(proposal), "proposed")
    }

    func test_init_seedsTodoIdsFromPersistedProposalsAlongsideSubmittedTaskIds() {
        let proposal = makeProposal(executionStatus: "added_to_todos", todoId: "todo-seeded")
        let store = MeetingActionProposalStore(proposals: [proposal], meetingId: "meeting-1", filename: "f.json")

        XCTAssertEqual(store.todoIds[proposal.id], "todo-seeded")
    }

    // MARK: - Edited draft promotion

    func test_submit_sendsEditedDraftAsSuggestedAgentTask() async throws {
        stubPromotionSuccess()
        stubProposalUpdateSuccess()
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )
        store.drafts[proposal.id] = "  Draft the recap with the new launch date.  "

        await store.submit(proposal)

        let promoteBody = try XCTUnwrap(capturedBodies(pathSuffix: "/api/v1/todos/meeting-proposals/promote").first)
        let body = try JSONSerialization.jsonObject(with: promoteBody) as? [String: Any]
        XCTAssertEqual(body?["suggested_agent_task"] as? String, "Draft the recap with the new launch date.")
    }

    // MARK: - startNow()

    func test_todoOnlyProposalCanStartAnAgentWorker() async throws {
        stubPromotionSuccess(todoId: "todo-xyz")
        stubWorkerLaunchSuccess(todoId: "todo-xyz")
        stubProposalUpdateSuccess()
        let proposal = makeProposal(executionMode: "todo_only")
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis.json"
        )
        store.drafts[proposal.id] = "Research encryption key rotation options and summarize the trade-offs."

        XCTAssertTrue(store.canStart(proposal))
        await store.startNow(proposal)

        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote").count, 1)
        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/items/todo-xyz/workers").count, 1)
        let promoteBody = try XCTUnwrap(capturedBodies(pathSuffix: "/api/v1/todos/meeting-proposals/promote").first)
        let body = try JSONSerialization.jsonObject(with: promoteBody) as? [String: Any]
        XCTAssertEqual(
            body?["suggested_agent_task"] as? String,
            "Research encryption key rotation options and summarize the trade-offs."
        )
    }

    func test_startNow_promotesThenLaunchesWorkerWithExpectedRevision() async throws {
        stubPromotionSuccess(todoId: "todo-xyz")
        stubWorkerLaunchSuccess(todoId: "todo-xyz")
        stubProposalUpdateSuccess()
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.startNow(proposal)

        let promoteRequests = capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote")
        let workerRequests = capturedRequests(pathSuffix: "/api/v1/todos/items/todo-xyz/workers")
        XCTAssertEqual(promoteRequests.count, 1)
        XCTAssertEqual(workerRequests.count, 1)
        let workerBodyData = try XCTUnwrap(capturedBodies(pathSuffix: "/api/v1/todos/items/todo-xyz/workers").first)
        let workerBody = try JSONSerialization.jsonObject(with: workerBodyData) as? [String: Any]
        XCTAssertEqual((workerBody?["expected_revision"] as? NSNumber)?.intValue, 1)
        XCTAssertEqual(store.todoIds[proposal.id], "todo-xyz")
        XCTAssertEqual(store.submittedTaskIds[proposal.id], "worker-returned")
        XCTAssertEqual(store.liveStatuses[proposal.id], .processing)
        XCTAssertEqual(store.statuses[proposal.id], "submitted")
        XCTAssertTrue(store.isHandled(store.effectiveStatus(proposal)))
    }

    func test_startNow_launchFailureKeepsTodoIdAndRemainsStartableButNotAddable() async {
        stubPromotionSuccess(todoId: "todo-xyz")
        stubWorkerLaunchFailure(todoId: "todo-xyz")
        stubProposalUpdateSuccess()
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(
            proposals: [proposal], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.startNow(proposal)

        XCTAssertEqual(store.todoIds[proposal.id], "todo-xyz")
        XCTAssertEqual(store.statuses[proposal.id], "failed")
        XCTAssertNotNil(store.errors[proposal.id])
        XCTAssertTrue(store.canStart(proposal))
        XCTAssertFalse(store.canSubmit(proposal))
        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/items/todo-xyz/workers").count, 1)
    }

    func test_startNow_withoutMeetingIdOrFilename_isANoOp() async {
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(proposals: [proposal], meetingId: nil, filename: nil)

        await store.startNow(proposal)

        XCTAssertNil(store.statuses[proposal.id])
        XCTAssertTrue(capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote").isEmpty)
        XCTAssertTrue(capturedRequests(pathSuffix: "/workers").isEmpty)
    }

    // MARK: - submitAllEligible()

    func test_submitAllEligible_includesProposedAndFailedWithoutTodoAndSkipsHandled() async {
        stubPromotionSuccess(todoId: "todo-bulk")
        let proposed = makeProposal(id: "proposal-proposed")
        let failedRetryable = makeProposal(id: "proposal-failed", executionStatus: "failed")
        let dismissed = makeProposal(id: "proposal-dismissed", executionStatus: "dismissed")
        let submitted = makeProposal(id: "proposal-submitted", executionStatus: "submitted")
        let completed = makeProposal(id: "proposal-completed", executionStatus: "completed")
        let added = makeProposal(id: "proposal-added", executionStatus: "added_to_todos", todoId: "todo-existing")
        let failedWithTodo = makeProposal(id: "proposal-failed-todo", executionStatus: "failed", todoId: "todo-kept")
        let store = MeetingActionProposalStore(
            proposals: [proposed, failedRetryable, dismissed, submitted, completed, added, failedWithTodo],
            meetingId: "meeting-1",
            filename: "analysis_20260101_000000.json"
        )

        await store.submitAllEligible()

        XCTAssertEqual(store.statuses[proposed.id], "added_to_todos")
        XCTAssertEqual(store.statuses[failedRetryable.id], "added_to_todos")
        XCTAssertNil(store.statuses[dismissed.id])
        XCTAssertNil(store.statuses[submitted.id])
        XCTAssertNil(store.statuses[completed.id])
        XCTAssertNil(store.statuses[added.id])
        XCTAssertNil(store.statuses[failedWithTodo.id])
        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote").count, 2)
        XCTAssertTrue(store.isEligibleForBulkPromotion(proposed) == false)
        XCTAssertFalse(store.canSubmit(failedWithTodo))
        XCTAssertTrue(store.canStart(failedWithTodo))
    }

    func test_submitAllEligible_oneFailureDoesNotRevertAnotherSuccess() async {
        TodoFixtureURLProtocol.promoteQueue = [
            .init(statusCode: 200, body: promotionBody(todoId: "todo-first", status: "open")),
            .init(statusCode: 500, body: Data(#"{"detail":"promotion failed"}"#.utf8)),
        ]
        let first = makeProposal(id: "proposal-1")
        let second = makeProposal(id: "proposal-2")
        let store = MeetingActionProposalStore(
            proposals: [first, second], meetingId: "meeting-1", filename: "analysis_20260101_000000.json"
        )

        await store.submitAllEligible()

        XCTAssertEqual(store.statuses[first.id], "added_to_todos")
        XCTAssertEqual(store.todoIds[first.id], "todo-first")
        XCTAssertEqual(store.statuses[second.id], "failed")
        XCTAssertNil(store.todoIds[second.id])
        XCTAssertNotNil(store.errors[second.id])
        XCTAssertEqual(capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote").count, 2)
    }

    func test_submitAllEligible_withoutMeetingIdOrFilename_isANoOp() async {
        let proposal = makeProposal()
        let store = MeetingActionProposalStore(proposals: [proposal], meetingId: nil, filename: nil)

        await store.submitAllEligible()

        XCTAssertNil(store.statuses[proposal.id])
        XCTAssertTrue(capturedRequests(pathSuffix: "/api/v1/todos/meeting-proposals/promote").isEmpty)
    }
}
