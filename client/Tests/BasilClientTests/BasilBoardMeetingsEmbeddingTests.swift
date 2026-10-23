import XCTest
@testable import BasilClient

@MainActor
final class BasilBoardMeetingsEmbeddingTests: XCTestCase {
    override func tearDown() {
        MeetingPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    private func webViewWithStubCoordinator() -> (BasilBoardWebView, MeetingSessionCoordinator) {
        let webView = BasilBoardWebView()
        let coordinator = MeetingSessionCoordinator()
        webView.meetingSessionCoordinatorProvider = { coordinator }
        return (webView, coordinator)
    }

    func testActivatingCreatesEmbeddedHostAttachedToSharedCoordinator() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertNotNil(webView.meetingAssistantEmbeddedHost)
        XCTAssertNotNil(coordinator.viewModel)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testDeactivatingTearsDownEmbeddedHostAndDetachesSession() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])

        XCTAssertNil(webView.meetingAssistantEmbeddedHost)
        XCTAssertNil(coordinator.viewModel)
    }

    func testNativeHostTeardownAlsoDetachesTheSession() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        webView.tearDown()

        XCTAssertNil(webView.meetingAssistantEmbeddedHost)
        XCTAssertNil(coordinator.viewModel)
    }

    func testRepeatedActivationCreatesOnlyOneHostUntilDeactivation() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        let firstHost = webView.meetingAssistantEmbeddedHost

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertTrue(webView.meetingAssistantEmbeddedHost === firstHost)
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
        XCTAssertNil(coordinator.viewModel)
    }

    func testConcurrentPresentationsShareOneSession() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        let boardModel = coordinator.viewModel
        let standaloneToken = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })

        XCTAssertTrue(coordinator.viewModel === boardModel)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
        XCTAssertNotNil(coordinator.viewModel)

        coordinator.detachPresentation(standaloneToken)
        XCTAssertNil(coordinator.viewModel)
    }

    func testEmbeddedWebViewInjectsMarkerAndUsesBoardGeometry() throws {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        let host = try XCTUnwrap(webView.meetingAssistantEmbeddedHost)
        let embeddedWebView = host.webView.webView
        let clippingContainer = try XCTUnwrap(embeddedWebView.superview)

        XCTAssertTrue(host.webView.isEmbedded)
        XCTAssertTrue(embeddedWebView.configuration.userContentController.userScripts.contains {
            $0.source.contains("meetingAssistantEmbedded")
        })
        XCTAssertEqual(clippingContainer.layer?.cornerRadius, 16)
        XCTAssertEqual(clippingContainer.layer?.maskedCorners, [.layerMaxXMaxYCorner])
        XCTAssertTrue(clippingContainer.layer?.masksToBounds ?? false)

        let hostConstraints = webView.webView.constraints
        // 56 = 4px basil-webkit-window-frame inset + either the 52px tab
        // rail (leading) or the bubble's true bottom edge past the header's
        // own 44px box (top) -- see BasilBoardWebView.embeddedTopInset/
        // embeddedLeadingInset.
        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .top, in: hostConstraints), 56)
        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .leading, in: hostConstraints), 56)
        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .trailing, in: hostConstraints), -8)
        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .bottom, in: hostConstraints), -8)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testMeasuredBoardChromeGeometryOverridesTheFallbackInsets() throws {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(
            name: "basilBoardBridge",
            body: ["type": "reportBoardChromeGeometry", "contentLeft": 58, "contentTop": 60]
        )
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        let host = try XCTUnwrap(webView.meetingAssistantEmbeddedHost)
        let clippingContainer = try XCTUnwrap(host.webView.webView.superview)
        let hostConstraints = webView.webView.constraints

        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .top, in: hostConstraints), 60)
        XCTAssertEqual(hostConstraintConstant(for: clippingContainer, attribute: .leading, in: hostConstraints), 58)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testDetachedBoardUsesOnlyTheFrameInsetWithNoLeadingRailInset() throws {
        let webView = BasilBoardWebView(detachedTabId: "meetings")
        let coordinator = MeetingSessionCoordinator()
        webView.meetingSessionCoordinatorProvider = { coordinator }
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        let host = try XCTUnwrap(webView.meetingAssistantEmbeddedHost)
        let clippingContainer = try XCTUnwrap(host.webView.webView.superview)
        // 4 = the bare basil-webkit-window-frame inset; a detached window
        // has no tab rail to additionally clear.
        XCTAssertEqual(
            hostConstraintConstant(
                for: clippingContainer,
                attribute: .leading,
                in: webView.webView.constraints
            ),
            4
        )
        // 48 = 4px frame inset + the detached header's plain 44px box (no
        // bubble bleed to clear on a detached window).
        XCTAssertEqual(
            hostConstraintConstant(
                for: clippingContainer,
                attribute: .top,
                in: webView.webView.constraints
            ),
            48
        )

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    private func hostConstraintConstant(
        for view: NSView,
        attribute: NSLayoutConstraint.Attribute,
        in constraints: [NSLayoutConstraint]
    ) -> CGFloat? {
        constraints.first(where: {
            (($0.firstItem as? NSView) === view && $0.firstAttribute == attribute)
                || (($0.secondItem as? NSView) === view && $0.secondAttribute == attribute)
        })?.constant
    }
}
