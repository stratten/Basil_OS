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

    func testOpenExternalUrlOpensWebAndMailLinksWithoutForwarding() {
        let webView = MeetingAssistantWebView()
        var opened: [URL] = []
        var forwardedCount = 0
        webView.openExternalLink = { opened.append($0) }
        webView.onIntent = { _, _ in forwardedCount += 1 }

        webView.handleMessage(body: ["type": "openExternalUrl", "url": "https://example.com/a?b=1"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": "HTTP://example.com/upper"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": "mailto:someone@example.com"])

        XCTAssertEqual(opened.map(\.absoluteString), [
            "https://example.com/a?b=1",
            "HTTP://example.com/upper",
            "mailto:someone@example.com",
        ])
        XCTAssertEqual(forwardedCount, 0)
        webView.tearDown()
    }

    func testOpenExternalUrlRefusesOtherSchemesAndMalformedPayloads() {
        let webView = MeetingAssistantWebView()
        var opened: [URL] = []
        webView.openExternalLink = { opened.append($0) }

        webView.handleMessage(body: ["type": "openExternalUrl", "url": "file:///etc/passwd"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": "javascript:alert(1)"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": "basil://settings"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": "not a url"])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": ""])
        webView.handleMessage(body: ["type": "openExternalUrl", "url": 42])
        webView.handleMessage(body: ["type": "openExternalUrl"])

        XCTAssertTrue(opened.isEmpty)
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

    func testCollapsedHeaderLeavesPauseAndEndClickableAndExpandingRestoresTheBubbleOnlyBand() throws {
        let webView = MeetingAssistantWebView()
        webView.installDragArea(headerHeight: 56)
        webView.handleMessage(body: ["type": "chromeHeight", "height": 52])

        // The compact window is 300pt wide. Pause spans 91...115pt and End 63...87pt from the right edge (3pt inset, 8pt padding, 44pt bubble, 6pt gap, 2pt padding, 24pt buttons, 4pt gap).
        webView.updateDragAreaForCollapse(true)
        let collapsedArea = try XCTUnwrap(webView.dragAreaView)
        collapsedArea.frame = NSRect(x: 0, y: 0, width: 300, height: 52)
        XCTAssertEqual(webView.dragAreaHeightConstraint?.constant, 52, "re-installing must keep the height the renderer reported")
        XCTAssertNil(collapsedArea.hitTest(NSPoint(x: 300 - 103, y: 26)), "Pause must receive the click")
        XCTAssertNil(collapsedArea.hitTest(NSPoint(x: 300 - 75, y: 26)), "End must receive the click")
        XCTAssertTrue(collapsedArea.hitTest(NSPoint(x: 300 - 129, y: 26)) === collapsedArea, "the title area stays draggable")

        webView.updateDragAreaForCollapse(false)
        let expandedArea = try XCTUnwrap(webView.dragAreaView)
        expandedArea.frame = NSRect(x: 0, y: 0, width: 920, height: 52)
        XCTAssertNil(expandedArea.hitTest(NSPoint(x: 920 - 40, y: 26)), "the bubble still passes through")
        XCTAssertTrue(expandedArea.hitTest(NSPoint(x: 920 - 100, y: 26)) === expandedArea, "an expanded header keeps the narrow band")
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
