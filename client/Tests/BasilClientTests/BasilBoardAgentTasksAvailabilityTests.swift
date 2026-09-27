import XCTest
@testable import BasilClient

@MainActor
final class BasilBoardAgentTasksAvailabilityTests: XCTestCase {
    override func tearDown() {
        AgentTaskResultPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testActivatingRegistersBoardVisibility() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])

        XCTAssertTrue(AgentTaskResultPresentationCoordinator.shared.isBoardVisible)
    }

    func testDeactivatingClearsBoardVisibility() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])

        XCTAssertFalse(AgentTaskResultPresentationCoordinator.shared.isBoardVisible)
    }

    func testNativeHostTeardownClearsBoardVisibilityAndEmbeddedHost() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        XCTAssertNotNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        webView.tearDown()

        XCTAssertFalse(AgentTaskResultPresentationCoordinator.shared.isBoardVisible)
        XCTAssertNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)
    }

    func testActivatingWhileStandaloneVisibleLeavesStandaloneAuthoritative() {
        AgentTaskResultPresentationCoordinator.shared.standaloneDidBecomeVisible()
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])

        XCTAssertEqual(AgentTaskResultPresentationCoordinator.shared.activePresenter, .standalone)
        AgentTaskResultPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testRepeatedActivationWithoutDeactivateStillClearsOnSingleDeactivate() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])

        XCTAssertFalse(AgentTaskResultPresentationCoordinator.shared.isBoardVisible)
    }

    func testActivatingWhenNoStandaloneCreatesEmbeddedHostAndReportsEmbedded() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])

        let embeddedHost = AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost
        XCTAssertNotNil(embeddedHost)
        XCTAssertEqual(embeddedHost?.webView.initialSidebarExpanded, true)
        XCTAssertEqual(embeddedHost?.webView.isEmbedded, true)
        XCTAssertTrue(embeddedHost?.webView.webView.configuration.userContentController.userScripts.contains(
            where: { $0.source.contains("agentTaskEmbedded") }
        ) == true)
        let embeddedWebView = embeddedHost!.webView.webView
        let clippingContainer = try! XCTUnwrap(embeddedWebView.superview)
        let boardHost = try! XCTUnwrap(clippingContainer.superview)
        XCTAssertTrue(clippingContainer.wantsLayer)
        XCTAssertEqual(clippingContainer.layer?.cornerRadius, 16)
        XCTAssertEqual(clippingContainer.layer?.maskedCorners, [.layerMaxXMaxYCorner])
        XCTAssertTrue(clippingContainer.layer?.masksToBounds ?? false)
        XCTAssertTrue(embeddedWebView.wantsLayer)
        XCTAssertEqual(embeddedWebView.layer?.cornerRadius, 16)
        XCTAssertEqual(embeddedWebView.layer?.maskedCorners, [.layerMaxXMaxYCorner])
        XCTAssertTrue(embeddedWebView.layer?.masksToBounds ?? false)

        let hostConstraints = boardHost.constraints
        let topConstant = hostConstraints.first(where: {
            (($0.firstItem as? NSView) === clippingContainer && $0.firstAttribute == .top)
                || (($0.secondItem as? NSView) === clippingContainer && $0.secondAttribute == .top)
        })?.constant
        let leadingConstant = hostConstraints.first(where: {
            (($0.firstItem as? NSView) === clippingContainer && $0.firstAttribute == .leading)
                || (($0.secondItem as? NSView) === clippingContainer && $0.secondAttribute == .leading)
        })?.constant
        let trailingConstant = hostConstraints.first(where: {
            (($0.firstItem as? NSView) === clippingContainer && $0.firstAttribute == .trailing)
                || (($0.secondItem as? NSView) === clippingContainer && $0.secondAttribute == .trailing)
        })?.constant
        let bottomConstant = hostConstraints.first(where: {
            (($0.firstItem as? NSView) === clippingContainer && $0.firstAttribute == .bottom)
                || (($0.secondItem as? NSView) === clippingContainer && $0.secondAttribute == .bottom)
        })?.constant
        // 56 = 4px basil-webkit-window-frame inset + either the 52px tab
        // rail (leading) or the bubble's true bottom edge past the header's
        // own 44px box (top) -- see BasilBoardWebView.embeddedTopInset/
        // embeddedLeadingInset.
        XCTAssertEqual(topConstant, 56)
        XCTAssertEqual(leadingConstant, 56)
        XCTAssertEqual(trailingConstant, -8)
        XCTAssertEqual(bottomConstant, -8)

        let embeddedConstraints = clippingContainer.constraints
        XCTAssertEqual(embeddedConstraints.filter { constraint in
            (constraint.firstItem as? NSView) === embeddedWebView
                || (constraint.secondItem as? NSView) === embeddedWebView
        }.count, 4)
        XCTAssertEqual(AgentTaskResultPresentationCoordinator.shared.activePresenter, .board)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
    }

    func testActivatingWhileStandaloneVisibleReportsSeparateWindowWithoutCreatingHost() {
        AgentTaskResultPresentationCoordinator.shared.standaloneDidBecomeVisible()
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])

        XCTAssertNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
        AgentTaskResultPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testStandaloneBecomingVisibleTearsDownAnExistingEmbeddedHost() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        XCTAssertNotNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        AgentTaskResultPresentationCoordinator.shared.standaloneDidBecomeVisible()
        XCTAssertNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
        AgentTaskResultPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testStandaloneDismissingRecreatesEmbeddedHost() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardAgentTasksSurface"])
        AgentTaskResultPresentationCoordinator.shared.standaloneDidBecomeVisible()
        XCTAssertNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        AgentTaskResultPresentationCoordinator.shared.standaloneDidDismiss()
        XCTAssertNotNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardAgentTasksSurface"])
    }
}
