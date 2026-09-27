import XCTest
@testable import BasilClient

@MainActor
final class MeetingPresentationArbitrationTests: XCTestCase {
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

    func testActivatingRegistersBoardVisibility() {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertTrue(MeetingPresentationCoordinator.shared.isBoardVisible)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testDeactivatingClearsBoardVisibility() {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])

        XCTAssertFalse(MeetingPresentationCoordinator.shared.isBoardVisible)
    }

    func testNativeHostTeardownClearsBoardVisibilityAndEmbeddedHost() {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        XCTAssertNotNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)

        webView.tearDown()

        XCTAssertFalse(MeetingPresentationCoordinator.shared.isBoardVisible)
        XCTAssertNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)
    }

    func testActivatingWhileStandaloneVisibleLeavesStandaloneAuthoritative() {
        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertEqual(MeetingPresentationCoordinator.shared.activePresenter, .standalone)
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
        MeetingPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testActivatingWhenNoStandaloneCreatesEmbeddedHostAndReportsBoardAuthoritative() {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertNotNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)
        XCTAssertEqual(MeetingPresentationCoordinator.shared.activePresenter, .board)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testActivatingWhileStandaloneVisibleReportsSeparateWindowWithoutCreatingHost() {
        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])

        XCTAssertNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
        MeetingPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testStandaloneBecomingVisibleTearsDownAnExistingEmbeddedHost() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        XCTAssertNotNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)
        XCTAssertNotNil(coordinator.viewModel)

        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
        XCTAssertNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)
        // The shared session survives: tearing down the embedded host only
        // detaches its own presentation token, and no other presentation
        // exists yet in this test, so the session does drop here -- proven
        // separately by the plain detach behavior in
        // BasilBoardMeetingsEmbeddingTests. This test's focus is purely the
        // arbitration/host lifecycle, not session lifetime.

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
        MeetingPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testStandaloneDismissingRecreatesEmbeddedHost() {
        let (webView, _) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
        XCTAssertNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)

        MeetingPresentationCoordinator.shared.standaloneDidDismiss()
        XCTAssertNotNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }

    func testShowWebMeetingRaisesBoardWindowInsteadOfOpeningStandaloneWhenBoardAuthoritative() {
        let (webView, coordinator) = webViewWithStubCoordinator()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardMeetingsSurface"])
        XCTAssertNotNil(MeetingPresentationCoordinator.shared.activeEmbeddedHost)

        coordinator.showWebMeeting()

        // No standalone panel was created: the coordinator's own
        // presentation-authority state stays exactly as it was before the
        // call (still `.board`), proving `showWebMeeting()` short-circuited
        // into raising the existing embedded host's window rather than
        // constructing `MeetingAssistantWindowController`.
        XCTAssertEqual(MeetingPresentationCoordinator.shared.activePresenter, .board)
        XCTAssertFalse(MeetingPresentationCoordinator.shared.isStandaloneVisible)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardMeetingsSurface"])
    }
}
