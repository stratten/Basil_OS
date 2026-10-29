import XCTest
@testable import BasilClient

@MainActor
final class StartupLoadingWebViewTests: XCTestCase {
    func testRejectsMissingAndUnsupportedProtocolVersions() {
        let host = StartupLoadingWebView()
        var didClose = false
        host.onClose = { didClose = true }

        host.handleMessage(body: ["type": "close"])
        host.handleMessage(body: ["type": "close", "protocolVersion": 2])

        XCTAssertFalse(didClose)
        host.tearDown()
    }

    func testForwardsEachWindowAction() {
        let host = StartupLoadingWebView()
        var didDrawnIn = false
        var didClose = false
        var didMinimize = false
        var didCollapse = false
        var didExpand = false
        host.onDrawnIn = { didDrawnIn = true }
        host.onClose = { didClose = true }
        host.onMinimize = { didMinimize = true }
        host.onCollapse = { didCollapse = true }
        host.onExpand = { didExpand = true }

        host.handleMessage(body: ["type": "drawnIn", "protocolVersion": 1])
        host.handleMessage(body: ["type": "close", "protocolVersion": 1])
        host.handleMessage(body: ["type": "minimize", "protocolVersion": 1])
        host.handleMessage(body: ["type": "collapse", "protocolVersion": 1])
        host.handleMessage(body: ["type": "expand", "protocolVersion": 1])

        XCTAssertTrue(didDrawnIn)
        XCTAssertTrue(didClose)
        XCTAssertTrue(didMinimize)
        XCTAssertTrue(didCollapse)
        XCTAssertTrue(didExpand)
        host.tearDown()
    }

    func testReadyAndNavigationFailureUseTheirDedicatedCallbacks() {
        let host = StartupLoadingWebView()
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
        let host = StartupLoadingWebView()
        host.resourcesURLProvider = { URL(fileURLWithPath: "/definitely-missing-startup-loading-window-assets") }
        var didFailNavigation = false
        host.onNavigationFailed = { didFailNavigation = true }

        host.loadContent(message: "Starting Basil...")

        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }

    func testDidFinishNavigationWithoutLoadContentTriggersFallbackCallback() {
        let host = StartupLoadingWebView()
        var didFailNavigation = false
        host.onNavigationFailed = { didFailNavigation = true }

        host.webView(host.webView, didFinish: nil)

        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }
}
