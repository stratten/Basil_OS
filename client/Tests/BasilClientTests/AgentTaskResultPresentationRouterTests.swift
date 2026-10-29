import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskResultPresentationRouterTests: XCTestCase {
    override func tearDown() {
        AgentTaskResultPresentationCoordinator.shared.resetForTesting()
        AgentTaskResultWidgetController.shared?.dismiss()
        super.tearDown()
    }

    func testStandaloneWidgetUsesSharedOpeningWidthAndConditionalMinimums() {
        XCTAssertEqual(AgentTaskResultWidgetController.standaloneMinimumSize(sidebarExpanded: false).width, 444)
        XCTAssertEqual(AgentTaskResultWidgetController.standaloneInitialSize(sidebarExpanded: false).width, 444)
        XCTAssertEqual(AgentTaskResultWidgetController.standaloneMinimumSize(sidebarExpanded: true).width, 636)
        XCTAssertEqual(AgentTaskResultWidgetController.standaloneInitialSize(sidebarExpanded: true).width, 444)
    }

    func testExpandedSidebarMinimumDoesNotInflateTheInitialFrame() {
        let initialSize = AgentTaskResultWidgetController.standaloneInitialSize(sidebarExpanded: true)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: initialSize),
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )

        window.minSize = AgentTaskResultWidgetController.standaloneMinimumSize(sidebarExpanded: true)

        XCTAssertEqual(window.frame.width, 444)
    }

    func testInstallNewAgentRoutesToEmbeddedHostWhenBoardAuthoritative() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        guard let host = AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost else {
            XCTFail("Expected embedded host")
            return
        }

        let routed = AgentTaskResultPresentationRouter.installNewAgent(
            agentTaskId: "embedded-task",
            initialAgentTask: "hello"
        )

        XCTAssertTrue(routed)
        XCTAssertEqual(host.pendingWebCommands.count, 1)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
    }

    func testInstallNewAgentFallsBackToStandaloneWhenNeitherVisible() {
        let routed = AgentTaskResultPresentationRouter.installNewAgent(
            agentTaskId: "standalone-task",
            initialAgentTask: "hello"
        )

        XCTAssertFalse(routed)
        XCTAssertNotNil(AgentTaskResultWidgetController.shared)
        AgentTaskResultWidgetController.shared?.dismiss()
    }

    func testShowExistingAgentTaskRoutesToEmbeddedHostWhenBoardAuthoritative() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        guard let host = AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost else {
            XCTFail("Expected embedded host")
            return
        }

        AgentTaskResultPresentationRouter.showExistingAgentTask(agentTaskId: "existing-task")
        XCTAssertEqual(host.pendingWebCommands.count, 1)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
    }
}
