import Foundation
import XCTest
@testable import BasilClient

@MainActor
final class ExecutionApprovalSettingsRegressionTests: XCTestCase {
    func testFailedApprovalLoadShowsAnErrorInsteadOfDefaultingToAnEmptyWhitelist() async {
        let apiClient = APIClient(performsInitialHealthCheck: false)
        apiClient.isBackendAvailable = false
        let viewModel = PermissionsSettingsViewModel(apiClient: apiClient)

        await viewModel.loadApprovalData()

        XCTAssertNil(viewModel.approvalSettings)
        XCTAssertTrue(viewModel.whitelistPatterns.isEmpty)
        XCTAssertTrue(
            viewModel.errorMessage?.hasPrefix("Failed to load command approval settings:") == true
        )
    }

    func testNativeApprovalClientUsesTheRegisteredAgentTaskRouteFamily() throws {
        let clientSourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Sources/Services/APIClient/APIClient_execution_approval.swift")
        let source = try String(contentsOf: clientSourceURL, encoding: .utf8)

        XCTAssertFalse(source.contains("/api/collaborative-workflow/"))
        XCTAssertEqual(
            source.components(separatedBy: "/api/v1/agent-tasks/approval/settings").count - 1,
            2
        )
        XCTAssertEqual(
            source.components(separatedBy: "/api/v1/agent-tasks/whitelist").count - 1,
            4
        )
    }

    func testNativeSessionClientsUseTheRegisteredAgentTaskRouteFamily() throws {
        let clientRootURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sessionSource = try String(
            contentsOf: clientRootURL.appendingPathComponent(
                "Sources/Services/APIClient/AgentTask/APIClient_agent_task_session_control.swift"
            ),
            encoding: .utf8
        )
        let recoverySource = try String(
            contentsOf: clientRootURL.appendingPathComponent(
                "Sources/Services/APIClient/AgentTask/APIClient_agent_task_recovery.swift"
            ),
            encoding: .utf8
        )

        XCTAssertFalse(sessionSource.contains("/api/collaborative-workflow/"))
        XCTAssertFalse(sessionSource.contains("/pause"))
        XCTAssertFalse(sessionSource.contains("/resume"))
        XCTAssertFalse(sessionSource.contains("/interactions"))
        XCTAssertFalse(sessionSource.contains("/sessions/active"))
        XCTAssertFalse(recoverySource.contains("/api/collaborative-workflow/"))
        XCTAssertTrue(sessionSource.contains("/api/v1/agent-tasks/sessions/"))
        XCTAssertTrue(recoverySource.contains("/api/v1/agent-tasks/sessions/"))
    }
}
