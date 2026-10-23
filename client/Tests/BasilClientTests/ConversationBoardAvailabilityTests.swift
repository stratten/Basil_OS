import XCTest
@testable import BasilClient

@MainActor
final class ConversationBoardAvailabilityTests: XCTestCase {
    override func tearDown() {
        ConversationPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testActivatingRegistersBoardVisibility() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])

        XCTAssertTrue(ConversationPresentationCoordinator.shared.isBoardVisible)
    }

    func testDeactivatingClearsBoardVisibility() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardConversationSurface"])

        XCTAssertFalse(ConversationPresentationCoordinator.shared.isBoardVisible)
    }

    func testNativeHostTeardownClearsBoardVisibility() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])

        webView.tearDown()

        XCTAssertFalse(ConversationPresentationCoordinator.shared.isBoardVisible)
    }

    func testActivatingWhileStandaloneVisibleLeavesStandaloneAuthoritative() {
        ConversationPresentationCoordinator.shared.standaloneDidBecomeVisible()
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])

        XCTAssertEqual(ConversationPresentationCoordinator.shared.activePresenter, .standalone)

        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardConversationSurface"])
        ConversationPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func testRepeatedActivationWithoutDeactivateStillClearsOnSingleDeactivate() {
        let webView = BasilBoardWebView()
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "activateBoardConversationSurface"])
        webView.handleMessage(name: "basilBoardBridge", body: ["type": "deactivateBoardConversationSurface"])

        XCTAssertFalse(ConversationPresentationCoordinator.shared.isBoardVisible)
    }
}
