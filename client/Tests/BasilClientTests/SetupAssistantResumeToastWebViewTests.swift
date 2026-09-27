import XCTest
@testable import BasilClient

@MainActor
final class SetupAssistantResumeToastWebViewTests: XCTestCase {
    func testRejectsMissingAndUnsupportedProtocolVersions() {
        let host = SetupAssistantResumeToastWebView()
        var didResume = false
        host.onResume = { didResume = true }

        host.handleMessage(body: ["type": "resume"])
        host.handleMessage(body: ["type": "resume", "protocolVersion": 2])

        XCTAssertFalse(didResume)
        host.tearDown()
    }

    func testForwardsEachDiscreteAction() {
        let host = SetupAssistantResumeToastWebView()
        var didResume = false
        var didRemindLater = false
        var didDontRemind = false
        host.onResume = { didResume = true }
        host.onRemindLater = { didRemindLater = true }
        host.onDontRemind = { didDontRemind = true }

        host.handleMessage(body: ["type": "resume", "protocolVersion": 1])
        host.handleMessage(body: ["type": "remindLater", "protocolVersion": 1])
        host.handleMessage(body: ["type": "dontRemind", "protocolVersion": 1])

        XCTAssertTrue(didResume)
        XCTAssertTrue(didRemindLater)
        XCTAssertTrue(didDontRemind)
        host.tearDown()
    }

    func testForwardsOnlyBoundedFiniteResizeRequests() {
        let host = SetupAssistantResumeToastWebView()
        var requestedSize: CGSize?
        host.onResizeRequested = { requestedSize = $0 }

        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 100, "height": 150])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 320, "height": 500])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": Double.nan, "height": 150])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 320, "height": 150])

        XCTAssertEqual(requestedSize, CGSize(width: 320, height: 150))
        host.tearDown()
    }

    func testReadyAndNavigationFailureUseTheirDedicatedCallbacks() {
        let host = SetupAssistantResumeToastWebView()
        var didReceiveReady = false
        var didFailNavigation = false
        host.onRendererReady = { didReceiveReady = true }
        host.onNavigationFailed = { didFailNavigation = true }

        host.handleMessage(body: ["type": "rendererReady", "protocolVersion": 1])
        host.webView(host.webView, didFail: nil, withError: NSError(domain: "test", code: 1))

        XCTAssertTrue(didReceiveReady)
        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }

    func testMissingStagedEntryTriggersFallbackCallback() {
        let host = SetupAssistantResumeToastWebView()
        host.resourcesURLProvider = { URL(fileURLWithPath: "/definitely-missing-setup-assistant-resume-toast-assets") }
        var didFailNavigation = false
        host.onNavigationFailed = { didFailNavigation = true }

        host.loadContent()

        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }

    func testDidFinishNavigationWithoutLoadContentTriggersFallbackCallback() {
        let host = SetupAssistantResumeToastWebView()
        var didFailNavigation = false
        host.onNavigationFailed = { didFailNavigation = true }

        host.webView(host.webView, didFinish: nil)

        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }
}
