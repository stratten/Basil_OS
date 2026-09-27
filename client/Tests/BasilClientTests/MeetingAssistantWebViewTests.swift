import XCTest
@testable import BasilClient

@MainActor
final class MeetingAssistantWebViewTests: XCTestCase {
    func testMalformedMessageBodyIsDroppedWithoutCrashing() {
        let webView = MeetingAssistantWebView()
        var closeCalled = false
        webView.onClose = { closeCalled = true }

        webView.handleMessage(body: ["type": "closeWindow"])
        XCTAssertTrue(closeCalled)

        closeCalled = false
        webView.handleMessage(body: "not-a-dictionary")
        XCTAssertFalse(closeCalled, "a non-dictionary body must be dropped, not treated as closeWindow")

        webView.handleMessage(body: ["type": "totallyUnknownIntent"])
        XCTAssertFalse(closeCalled, "an unrecognized type string must be dropped")

        webView.tearDown()
    }

    func testKnownDomainIntentIsForwardedWithPayload() {
        let webView = MeetingAssistantWebView()
        var forwarded: (MeetingBridgeIntent, [String: Any])?
        webView.onIntent = { intent, payload in forwarded = (intent, payload) }

        webView.handleMessage(body: ["type": "selectMeeting", "meetingId": "abc-123"])
        XCTAssertEqual(forwarded?.0, .selectMeeting)
        XCTAssertEqual(forwarded?.1["meetingId"] as? String, "abc-123")

        webView.tearDown()
    }

    func testReactReadyRequiresSupportedProtocolVersion() {
        let webView = MeetingAssistantWebView()
        var forwardedCount = 0
        webView.onIntent = { _, _ in forwardedCount += 1 }

        webView.handleMessage(body: ["type": "reactReady", "protocolVersion": meetingBridgeProtocolVersion - 1])
        XCTAssertEqual(forwardedCount, 0)
        XCTAssertFalse(webView.hasReceivedReady)

        webView.handleMessage(body: ["type": "reactReady", "protocolVersion": meetingBridgeProtocolVersion])
        XCTAssertEqual(forwardedCount, 1)
        XCTAssertTrue(webView.hasReceivedReady)

        webView.tearDown()
    }

    func testChromeHeightUpdatesDragOverlayHeightWithoutForwardingIntent() {
        let webView = MeetingAssistantWebView()
        webView.installDragArea()
        var forwardedCount = 0
        webView.onIntent = { _, _ in forwardedCount += 1 }

        webView.handleMessage(body: ["type": "chromeHeight", "height": 56])

        XCTAssertEqual(webView.dragAreaHeightConstraint?.constant, 56)
        XCTAssertEqual(forwardedCount, 0)
        webView.tearDown()
    }

    func testChromeHeightIgnoresNonFinitePositiveValues() {
        let webView = MeetingAssistantWebView()
        webView.installDragArea()
        let initialHeight = webView.dragAreaHeightConstraint?.constant

        webView.handleMessage(body: ["type": "chromeHeight", "height": 0])
        webView.handleMessage(body: ["type": "chromeHeight", "height": -5])

        XCTAssertEqual(webView.dragAreaHeightConstraint?.constant, initialHeight)
        webView.tearDown()
    }
}
