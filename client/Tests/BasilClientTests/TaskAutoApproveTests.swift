import Foundation
import XCTest
@testable import BasilClient

/// Answers only the auto-approve route, so it ignores unrelated traffic such as APIClient.shared's background health check.
final class TaskAutoApproveStubURLProtocol: URLProtocol {
    struct StubbedResponse {
        let statusCode: Int
        let body: Data
    }

    static var queuedResponses: [StubbedResponse] = []
    static var capturedRequests: [URLRequest] = []

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.path.hasPrefix("/api/v1/agent-tasks/auto-approve/") == true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        TaskAutoApproveStubURLProtocol.capturedRequests.append(request)
        guard let url = request.url, !TaskAutoApproveStubURLProtocol.queuedResponses.isEmpty else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }
        let stub = TaskAutoApproveStubURLProtocol.queuedResponses.removeFirst()
        let response = HTTPURLResponse(
            url: url,
            statusCode: stub.statusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: stub.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class TaskAutoApproveRequestTests: XCTestCase {
    func testEndpointUsesTheTaskIdAsOnePathSegment() {
        XCTAssertEqual(
            APIClient.taskAutoApproveEndpoint(rootTaskId: "9f0c2a4e-1111-2222-3333-444455556666"),
            "/api/v1/agent-tasks/auto-approve/9f0c2a4e-1111-2222-3333-444455556666"
        )
    }

    func testASlashOrOtherReservedCharacterCannotChangeTheRoute() {
        XCTAssertEqual(
            APIClient.taskAutoApproveEndpoint(rootTaskId: "a/b"),
            "/api/v1/agent-tasks/auto-approve/a%2Fb"
        )
        XCTAssertEqual(
            APIClient.taskAutoApproveEndpoint(rootTaskId: "../whitelist"),
            "/api/v1/agent-tasks/auto-approve/..%2Fwhitelist"
        )
        XCTAssertEqual(
            APIClient.taskAutoApproveEndpoint(rootTaskId: "a b?c"),
            "/api/v1/agent-tasks/auto-approve/a%20b%3Fc"
        )
    }

    func testABlankTaskIdHasNoRoute() {
        XCTAssertNil(APIClient.taskAutoApproveEndpoint(rootTaskId: ""))
        XCTAssertNil(APIClient.taskAutoApproveEndpoint(rootTaskId: "   "))
    }

    func testOutcomeDecodesTheBackendAnswer() throws {
        let outcome = try TaskAutoApproveOutcome.decode(Data(#"{"enabled":true,"approved_waiting":2}"#.utf8))

        XCTAssertEqual(outcome, TaskAutoApproveOutcome(enabled: true, approvedWaiting: 2))
    }

    func testOutcomeWithoutAWaitingCountMeansNone() throws {
        let outcome = try TaskAutoApproveOutcome.decode(Data(#"{"enabled":false}"#.utf8))

        XCTAssertEqual(outcome, TaskAutoApproveOutcome(enabled: false, approvedWaiting: 0))
    }

    func testOutcomeNeverReportsANegativeWaitingCount() throws {
        let outcome = try TaskAutoApproveOutcome.decode(Data(#"{"enabled":true,"approved_waiting":-3}"#.utf8))

        XCTAssertEqual(outcome.approvedWaiting, 0)
    }

    func testAnAnswerWithoutABooleanEnabledIsNotAnAnswer() {
        for body in [#"{}"#, #"{"enabled":"yes"}"#, #"[]"#, #"{"enabled":null}"#] {
            XCTAssertThrowsError(try TaskAutoApproveOutcome.decode(Data(body.utf8)), body)
        }
        XCTAssertThrowsError(try TaskAutoApproveOutcome.decode(Data("not json".utf8)))
    }
}

@MainActor
final class TaskAutoApproveRouteTests: XCTestCase {
    private var originalPresenter: ((ExecutionApprovalRiskPrompt) -> Bool)!
    private var presentedPrompts: [ExecutionApprovalRiskPrompt] = []

    private let confirmationBody = Data(
        #"{"detail":{"code":"risk_confirmation_required","title":"Approve every command for this task?","message":"Basil will run every command this task proposes without asking you first."}}"#.utf8
    )

    override func setUp() async throws {
        try await super.setUp()
        originalPresenter = ExecutionApprovalRiskConfirmation.presenter
        presentedPrompts = []
        TaskAutoApproveStubURLProtocol.queuedResponses = []
        TaskAutoApproveStubURLProtocol.capturedRequests = []
        URLProtocol.registerClass(TaskAutoApproveStubURLProtocol.self)
    }

    override func tearDown() async throws {
        URLProtocol.unregisterClass(TaskAutoApproveStubURLProtocol.self)
        ExecutionApprovalRiskConfirmation.presenter = originalPresenter
        originalPresenter = nil
        TaskAutoApproveStubURLProtocol.queuedResponses = []
        TaskAutoApproveStubURLProtocol.capturedRequests = []
        try await super.tearDown()
    }

    private func recordPrompts(answer: Bool) {
        ExecutionApprovalRiskConfirmation.presenter = { [weak self] prompt in
            self?.presentedPrompts.append(prompt)
            return answer
        }
    }

    private func queue(_ statusCode: Int, _ body: Data) {
        TaskAutoApproveStubURLProtocol.queuedResponses.append(.init(statusCode: statusCode, body: body))
    }

    private func availableClient() -> APIClient {
        let apiClient = APIClient(performsInitialHealthCheck: false)
        apiClient.isBackendAvailable = true
        return apiClient
    }

    func testEnablingAsksTheUserThenResendsWithTheConfirmationAndReportsTheOutcome() async throws {
        recordPrompts(answer: true)
        queue(428, confirmationBody)
        queue(200, Data(#"{"enabled":true,"approved_waiting":1}"#.utf8))

        let outcome = try await availableClient().setTaskAutoApprove(rootTaskId: "root-1", enabled: true)

        XCTAssertEqual(outcome, TaskAutoApproveOutcome(enabled: true, approvedWaiting: 1))
        XCTAssertEqual(presentedPrompts.map(\.title), ["Approve every command for this task?"])
        let requests = TaskAutoApproveStubURLProtocol.capturedRequests
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[0].httpMethod, "POST")
        XCTAssertEqual(requests[0].url?.path, "/api/v1/agent-tasks/auto-approve/root-1")
        XCTAssertNil(requests[0].value(forHTTPHeaderField: "X-Basil-Risk-Confirmed"))
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "X-Basil-Risk-Confirmed"), "true")
        let sentBody = try XCTUnwrap(requests[0].httpBodyStreamData ?? requests[0].httpBody)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: sentBody) as? [String: Bool], ["enabled": true])
    }

    func testDecliningTheConfirmationChangesNothingAndSendsNoSecondRequest() async {
        recordPrompts(answer: false)
        queue(428, confirmationBody)

        do {
            _ = try await availableClient().setTaskAutoApprove(rootTaskId: "root-1", enabled: true)
            XCTFail("Expected the declined confirmation to throw")
        } catch let error as ExecutionApprovalRiskConfirmationError {
            XCTAssertEqual(error, .declined)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertEqual(presentedPrompts.count, 1)
        XCTAssertEqual(TaskAutoApproveStubURLProtocol.capturedRequests.count, 1)
    }

    func testTurningItOffNeedsNoConfirmation() async throws {
        recordPrompts(answer: true)
        queue(200, Data(#"{"enabled":false,"approved_waiting":0}"#.utf8))

        let outcome = try await availableClient().setTaskAutoApprove(rootTaskId: "root-1", enabled: false)

        XCTAssertEqual(outcome, TaskAutoApproveOutcome(enabled: false, approvedWaiting: 0))
        XCTAssertTrue(presentedPrompts.isEmpty)
        XCTAssertEqual(TaskAutoApproveStubURLProtocol.capturedRequests.count, 1)
    }

    func testAnUnavailableBackendFailsBeforeAnyRequestOrPrompt() async {
        recordPrompts(answer: true)
        let apiClient = APIClient(performsInitialHealthCheck: false)
        apiClient.isBackendAvailable = false

        do {
            _ = try await apiClient.setTaskAutoApprove(rootTaskId: "root-1", enabled: true)
            XCTFail("Expected backendNotAvailable")
        } catch APIError.backendNotAvailable {
            // expected
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertTrue(presentedPrompts.isEmpty)
        XCTAssertTrue(TaskAutoApproveStubURLProtocol.capturedRequests.isEmpty)
    }

    func testABlankTaskIdFailsBeforeAnyRequest() async {
        do {
            _ = try await availableClient().setTaskAutoApprove(rootTaskId: "  ", enabled: true)
            XCTFail("Expected invalidURL")
        } catch APIError.invalidURL {
            // expected
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertTrue(TaskAutoApproveStubURLProtocol.capturedRequests.isEmpty)
    }

    func testABackendRefusalIsAFailureNotASuccess() async {
        queue(403, Data(#"{"detail":"host_credential_required"}"#.utf8))

        do {
            _ = try await availableClient().setTaskAutoApprove(rootTaskId: "root-1", enabled: false)
            XCTFail("Expected a server error")
        } catch APIError.serverError(let statusCode) {
            XCTAssertEqual(statusCode, 403)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}

private extension URLRequest {
    /// URLProtocol receives a request body as a stream rather than as `httpBody`.
    var httpBodyStreamData: Data? {
        guard let stream = httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data.isEmpty ? nil : data
    }
}

final class TaskAutoApproveBridgeTests: XCTestCase {
    private struct Boom: Error {}

    func testAnAcceptedChangeIsReportedAsAppliedWithTheBackendsState() async {
        let result = await TaskAutoApproveBridge.perform(requestId: "req-1", rootTaskId: "root-1", enabled: true) { rootTaskId, enabled in
            XCTAssertEqual(rootTaskId, "root-1")
            XCTAssertTrue(enabled)
            return TaskAutoApproveOutcome(enabled: true, approvedWaiting: 2)
        }

        XCTAssertEqual(result.status, .applied)
        XCTAssertTrue(result.enabled)
        XCTAssertEqual(result.approvedWaiting, 2)
        XCTAssertNil(result.message)
    }

    func testADeclinedConfirmationLeavesTheSwitchWhereItWasWithoutAnError() async {
        let result = await TaskAutoApproveBridge.perform(requestId: "req-1", rootTaskId: "root-1", enabled: true) { _, _ in
            throw ExecutionApprovalRiskConfirmationError.declined
        }

        XCTAssertEqual(result.status, .declined)
        XCTAssertFalse(result.enabled)
        XCTAssertEqual(result.approvedWaiting, 0)
        XCTAssertNil(result.message)
    }

    func testADeclinedTurnOffIsReportedAsStillOn() async {
        let result = await TaskAutoApproveBridge.perform(requestId: "req-1", rootTaskId: "root-1", enabled: false) { _, _ in
            throw ExecutionApprovalRiskConfirmationError.declined
        }

        XCTAssertEqual(result.status, .declined)
        XCTAssertTrue(result.enabled)
    }

    func testAFailureIsReportedWithAPlainMessageAndNeverTheUnderlyingError() async {
        let result = await TaskAutoApproveBridge.perform(requestId: "req-1", rootTaskId: "root-1", enabled: true) { _, _ in
            throw Boom()
        }

        XCTAssertEqual(result.status, .failed)
        XCTAssertFalse(result.enabled)
        XCTAssertEqual(result.message, TaskAutoApproveBridge.failureMessage)
        XCTAssertEqual(result.message, "Auto-approve could not be changed.")
    }

    func testTheResultCarriesTheShapeTheWebSideExpects() throws {
        let applied = TaskAutoApproveBridgeResult(
            requestId: "req-1",
            rootTaskId: "root-1",
            status: .applied,
            enabled: true,
            approvedWaiting: 3,
            message: nil
        ).jsonObject

        XCTAssertEqual(applied["requestId"] as? String, "req-1")
        XCTAssertEqual(applied["rootTaskId"] as? String, "root-1")
        XCTAssertEqual(applied["status"] as? String, "applied")
        XCTAssertEqual(applied["enabled"] as? Bool, true)
        XCTAssertEqual(applied["approvedWaiting"] as? Int, 3)
        XCTAssertNil(applied["message"])
        XCTAssertTrue(JSONSerialization.isValidJSONObject(applied))

        let failed = TaskAutoApproveBridgeResult(
            requestId: "req-2",
            rootTaskId: "root-1",
            status: .failed,
            enabled: false,
            approvedWaiting: 0,
            message: "Nope."
        ).jsonObject
        XCTAssertEqual(failed["status"] as? String, "failed")
        XCTAssertEqual(failed["message"] as? String, "Nope.")
    }
}

@MainActor
final class CaptureAutoApproveViewModelTests: XCTestCase {
    private func viewModel(preGeneratedId: String? = "new-task-1") -> AgentTaskCaptureViewModel {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.preGeneratedAgentTaskId = preGeneratedId
        return viewModel
    }

    func testEnablingSetsTheSwitchAgainstTheNewTasksPreGeneratedId() async {
        let model = viewModel()
        var asked: [(String, Bool)] = []

        await model.setTaskAutoApprove(true) { rootTaskId, enabled in
            asked.append((rootTaskId, enabled))
            return TaskAutoApproveOutcome(enabled: true, approvedWaiting: 0)
        }

        XCTAssertEqual(asked.count, 1)
        XCTAssertEqual(asked.first?.0, "new-task-1")
        XCTAssertEqual(asked.first?.1, true)
        XCTAssertTrue(model.taskAutoApproveEnabled)
        XCTAssertFalse(model.taskAutoApprovePending)
        XCTAssertNil(model.taskAutoApproveError)
    }

    func testAnExistingChainRootTakesPrecedenceOverThePreGeneratedId() {
        let model = AgentTaskCaptureViewModel(rootTaskId: "chain-root", previousTaskId: "chain-prev")
        model.preGeneratedAgentTaskId = "this-turn"

        XCTAssertEqual(model.autoApproveChainRootId, "chain-root")
    }

    func testNoIdAtAllMeansNoChainRoot() {
        XCTAssertNil(viewModel(preGeneratedId: nil).autoApproveChainRootId)
        XCTAssertNil(viewModel(preGeneratedId: "").autoApproveChainRootId)
    }

    func testWithNoChainRootNothingIsAsked() async {
        let model = viewModel(preGeneratedId: nil)
        var asked = 0

        await model.setTaskAutoApprove(true) { _, _ in
            asked += 1
            return TaskAutoApproveOutcome(enabled: true, approvedWaiting: 0)
        }

        XCTAssertEqual(asked, 0)
        XCTAssertFalse(model.taskAutoApproveEnabled)
    }

    func testADeclinedConfirmationKeepsItOffWithNoError() async {
        let model = viewModel()

        await model.setTaskAutoApprove(true) { _, _ in
            throw ExecutionApprovalRiskConfirmationError.declined
        }

        XCTAssertFalse(model.taskAutoApproveEnabled)
        XCTAssertFalse(model.taskAutoApprovePending)
        XCTAssertNil(model.taskAutoApproveError)
    }

    func testAFailureKeepsItOffAndShowsAPlainError() async {
        let model = viewModel()

        await model.setTaskAutoApprove(true) { _, _ in
            throw APIError.backendNotAvailable
        }

        XCTAssertFalse(model.taskAutoApproveEnabled)
        XCTAssertFalse(model.taskAutoApprovePending)
        XCTAssertEqual(model.taskAutoApproveError, "Auto-approve could not be changed.")
    }

    func testTryingAgainClearsTheEarlierError() async {
        let model = viewModel()
        await model.setTaskAutoApprove(true) { _, _ in throw APIError.backendNotAvailable }
        XCTAssertNotNil(model.taskAutoApproveError)

        await model.setTaskAutoApprove(true) { _, _ in TaskAutoApproveOutcome(enabled: true, approvedWaiting: 0) }

        XCTAssertTrue(model.taskAutoApproveEnabled)
        XCTAssertNil(model.taskAutoApproveError)
    }

    func testAskingForTheStateItIsAlreadyInSendsNothing() async {
        let model = viewModel()
        var asked = 0
        let change: TaskAutoApproveBridge.Change = { _, enabled in
            asked += 1
            return TaskAutoApproveOutcome(enabled: enabled, approvedWaiting: 0)
        }

        await model.setTaskAutoApprove(false, change: change)
        XCTAssertEqual(asked, 0)

        await model.setTaskAutoApprove(true, change: change)
        await model.setTaskAutoApprove(true, change: change)
        XCTAssertEqual(asked, 1)
    }

    func testItTurnsOffTheSameWay() async {
        let model = viewModel()
        await model.setTaskAutoApprove(true) { _, enabled in TaskAutoApproveOutcome(enabled: enabled, approvedWaiting: 0) }

        await model.setTaskAutoApprove(false) { _, enabled in TaskAutoApproveOutcome(enabled: enabled, approvedWaiting: 0) }

        XCTAssertFalse(model.taskAutoApproveEnabled)
    }

    func testASecondRequestWhileOneIsWaitingOnTheUserIsIgnored() async {
        let model = viewModel()
        var asked = 0
        let gate = AsyncGate()

        let first = Task { @MainActor in
            await model.setTaskAutoApprove(true) { _, _ in
                asked += 1
                await gate.wait()
                return TaskAutoApproveOutcome(enabled: true, approvedWaiting: 0)
            }
        }
        while !model.taskAutoApprovePending { await Task.yield() }

        await model.setTaskAutoApprove(false) { _, _ in
            asked += 1
            return TaskAutoApproveOutcome(enabled: false, approvedWaiting: 0)
        }
        XCTAssertEqual(asked, 1)
        XCTAssertTrue(model.taskAutoApprovePending)

        await gate.open()
        await first.value
        XCTAssertTrue(model.taskAutoApproveEnabled)
        XCTAssertFalse(model.taskAutoApprovePending)
    }
}

private actor AsyncGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}
