import Foundation
import XCTest
@testable import BasilClient

final class RiskConfirmationStubURLProtocol: URLProtocol {
    struct StubbedResponse {
        let statusCode: Int
        let body: Data
    }

    static var queuedResponses: [StubbedResponse] = []
    static var capturedRequests: [URLRequest] = []

    // Registered process-wide in one test, so it must ignore unrelated traffic such as APIClient.shared's background health check.
    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.path == "/api/v1/agent-tasks/whitelist"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        RiskConfirmationStubURLProtocol.capturedRequests.append(request)
        guard let url = request.url, !RiskConfirmationStubURLProtocol.queuedResponses.isEmpty else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }
        let stub = RiskConfirmationStubURLProtocol.queuedResponses.removeFirst()
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

@MainActor
final class ExecutionApprovalRiskConfirmationTests: XCTestCase {
    private var originalPresenter: ((ExecutionApprovalRiskPrompt) -> Bool)!
    private var presentedPrompts: [ExecutionApprovalRiskPrompt] = []
    private var session: URLSession!

    private let confirmationBody = Data(
        #"{"detail":{"code":"risk_confirmation_required","title":"Allow this command without asking?","message":"Commands matching the prefix pattern rm will run without an approval prompt."}}"#.utf8
    )

    override func setUp() async throws {
        try await super.setUp()
        originalPresenter = ExecutionApprovalRiskConfirmation.presenter
        presentedPrompts = []
        RiskConfirmationStubURLProtocol.queuedResponses = []
        RiskConfirmationStubURLProtocol.capturedRequests = []
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RiskConfirmationStubURLProtocol.self]
        session = URLSession(configuration: configuration)
    }

    override func tearDown() async throws {
        ExecutionApprovalRiskConfirmation.presenter = originalPresenter
        originalPresenter = nil
        session.invalidateAndCancel()
        session = nil
        RiskConfirmationStubURLProtocol.queuedResponses = []
        RiskConfirmationStubURLProtocol.capturedRequests = []
        try await super.tearDown()
    }

    private func recordPrompts(answer: Bool) {
        ExecutionApprovalRiskConfirmation.presenter = { [weak self] prompt in
            self?.presentedPrompts.append(prompt)
            return answer
        }
    }

    private func whitelistRequest() -> URLRequest {
        var request = URLRequest(url: URL(string: "http://localhost:8123/api/v1/agent-tasks/whitelist")!)
        request.httpMethod = "POST"
        request.httpBody = Data(#"{"pattern":"rm","pattern_type":"prefix"}"#.utf8)
        return request
    }

    private func queue(_ statusCode: Int, _ body: Data) {
        RiskConfirmationStubURLProtocol.queuedResponses.append(.init(statusCode: statusCode, body: body))
    }

    func testConfirmationPromptDecodesOnlyTheContract() {
        XCTAssertEqual(
            ExecutionApprovalRiskConfirmation.confirmationPrompt(statusCode: 428, data: confirmationBody),
            ExecutionApprovalRiskPrompt(
                title: "Allow this command without asking?",
                message: "Commands matching the prefix pattern rm will run without an approval prompt."
            )
        )
        XCTAssertNil(ExecutionApprovalRiskConfirmation.confirmationPrompt(statusCode: 400, data: confirmationBody))
        XCTAssertNil(ExecutionApprovalRiskConfirmation.confirmationPrompt(statusCode: 428, data: Data("not json".utf8)))
        XCTAssertNil(ExecutionApprovalRiskConfirmation.confirmationPrompt(statusCode: 428, data: Data(#"{"detail":"Precondition Required"}"#.utf8)))
        XCTAssertNil(ExecutionApprovalRiskConfirmation.confirmationPrompt(
            statusCode: 428,
            data: Data(#"{"detail":{"code":"something_else","title":"T","message":"M"}}"#.utf8)
        ))
        XCTAssertNil(ExecutionApprovalRiskConfirmation.confirmationPrompt(
            statusCode: 428,
            data: Data(#"{"detail":{"code":"risk_confirmation_required","title":"","message":"M"}}"#.utf8)
        ))
    }

    func testNonConfirmationResponsesReturnWithoutPrompting() async throws {
        recordPrompts(answer: true)
        queue(200, Data(#"{"ok":true}"#.utf8))

        let (data, response) = try await ExecutionApprovalRiskConfirmation.send(whitelistRequest(), session: session)

        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
        XCTAssertEqual(data, Data(#"{"ok":true}"#.utf8))
        XCTAssertTrue(presentedPrompts.isEmpty)
        XCTAssertEqual(RiskConfirmationStubURLProtocol.capturedRequests.count, 1)
    }

    func testDecliningThrowsAndSendsNoSecondRequest() async throws {
        recordPrompts(answer: false)
        queue(428, confirmationBody)

        do {
            _ = try await ExecutionApprovalRiskConfirmation.send(whitelistRequest(), session: session)
            XCTFail("Expected the declined confirmation to throw")
        } catch let error as ExecutionApprovalRiskConfirmationError {
            XCTAssertEqual(error, .declined)
        }

        XCTAssertEqual(presentedPrompts.map(\.title), ["Allow this command without asking?"])
        XCTAssertEqual(RiskConfirmationStubURLProtocol.capturedRequests.count, 1)
    }

    func testConfirmingResendsTheSameRequestWithTheConfirmationHeader() async throws {
        recordPrompts(answer: true)
        queue(428, confirmationBody)
        queue(200, Data(#"{"ok":true}"#.utf8))

        let (_, response) = try await ExecutionApprovalRiskConfirmation.send(whitelistRequest(), session: session)

        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
        let requests = RiskConfirmationStubURLProtocol.capturedRequests
        XCTAssertEqual(requests.count, 2)
        XCTAssertNil(requests[0].value(forHTTPHeaderField: "X-Basil-Risk-Confirmed"))
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "X-Basil-Risk-Confirmed"), "true")
        XCTAssertEqual(requests[1].httpMethod, "POST")
        XCTAssertEqual(requests[1].url, requests[0].url)
        XCTAssertEqual(presentedPrompts.count, 1)
    }

    func testMalformedConfirmationBodyIsReturnedUnchanged() async throws {
        recordPrompts(answer: true)
        queue(428, Data(#"{"detail":"Precondition Required"}"#.utf8))

        let (_, response) = try await ExecutionApprovalRiskConfirmation.send(whitelistRequest(), session: session)

        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 428)
        XCTAssertTrue(presentedPrompts.isEmpty)
        XCTAssertEqual(RiskConfirmationStubURLProtocol.capturedRequests.count, 1)
    }

    func testUnavailableBackendFailsBeforePrompting() async {
        let apiClient = APIClient(performsInitialHealthCheck: false)
        apiClient.isBackendAvailable = false
        recordPrompts(answer: true)

        do {
            _ = try await apiClient.addWhitelistPattern(AddWhitelistRequest(pattern: "rm", patternType: "prefix"))
            XCTFail("Expected backendNotAvailable")
        } catch {
            XCTAssertTrue(presentedPrompts.isEmpty)
        }
    }

    func testAPIClientWhitelistAddRoutesThroughTheConfirmation() async {
        URLProtocol.registerClass(RiskConfirmationStubURLProtocol.self)
        defer { URLProtocol.unregisterClass(RiskConfirmationStubURLProtocol.self) }
        let apiClient = APIClient(performsInitialHealthCheck: false)
        apiClient.isBackendAvailable = true
        recordPrompts(answer: false)
        queue(428, confirmationBody)

        do {
            _ = try await apiClient.addWhitelistPattern(AddWhitelistRequest(pattern: "rm", patternType: "prefix"))
            XCTFail("Expected the declined confirmation to throw")
        } catch let error as ExecutionApprovalRiskConfirmationError {
            XCTAssertEqual(error, .declined)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertEqual(presentedPrompts.count, 1)
        XCTAssertEqual(RiskConfirmationStubURLProtocol.capturedRequests.count, 1)
    }
}
