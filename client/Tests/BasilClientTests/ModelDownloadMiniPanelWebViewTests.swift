import XCTest
@testable import BasilClient

@MainActor
final class ModelDownloadMiniPanelWebViewTests: XCTestCase {
    func testRejectsMissingAndUnsupportedProtocolVersions() {
        let host = ModelDownloadMiniPanelWebView()
        var didDismiss = false
        host.onDismiss = { didDismiss = true }

        host.handleMessage(body: ["type": "dismiss"])
        host.handleMessage(body: ["type": "dismiss", "protocolVersion": 2])

        XCTAssertFalse(didDismiss)
        host.tearDown()
    }

    func testForwardsValidKnownModelActionsOnly() {
        let host = ModelDownloadMiniPanelWebView()
        host.isKnownModelId = { $0 == "OpenAI-whisper-tiny.en" }
        var retriedModelId: String?
        var canceledModelId: String?
        host.onRetryModel = { retriedModelId = $0 }
        host.onCancelModel = { canceledModelId = $0 }

        host.handleMessage(body: ["type": "retryModel", "protocolVersion": 1, "modelId": "unknown"])
        host.handleMessage(body: ["type": "cancelModel", "protocolVersion": 1, "modelId": ""])
        host.handleMessage(body: ["type": "retryModel", "protocolVersion": 1, "modelId": "OpenAI-whisper-tiny.en"])
        host.handleMessage(body: ["type": "cancelModel", "protocolVersion": 1, "modelId": "OpenAI-whisper-tiny.en"])

        XCTAssertEqual(retriedModelId, "OpenAI-whisper-tiny.en")
        XCTAssertEqual(canceledModelId, "OpenAI-whisper-tiny.en")
        host.tearDown()
    }

    func testForwardsOnlyBoundedFiniteResizeRequests() {
        let host = ModelDownloadMiniPanelWebView()
        var requestedSize: CGSize?
        host.onResizeRequested = { requestedSize = $0 }

        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 100, "height": 220])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 272, "height": 500])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": Double.nan, "height": 220])
        host.handleMessage(body: ["type": "requestResize", "protocolVersion": 1, "width": 272, "height": 140])

        XCTAssertEqual(requestedSize, CGSize(width: 272, height: 140))
        host.tearDown()
    }

    func testSnapshotSerializesNullableByteCounts() throws {
        let snapshot = ModelDownloadPanelSnapshot(
            phaseMessage: "Preparing...",
            isComplete: false,
            quantizedPercentage: 0,
            appIconDataUrl: nil,
            models: [.init(modelId: "unknown", status: "pending", progress: 0, totalDownloaded: nil, totalSize: nil, isRetrying: false)]
        )

        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject())
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let models = object?["models"] as? [[String: Any]]

        XCTAssertTrue(object?["appIconDataUrl"] is NSNull)
        XCTAssertTrue(models?.first?["totalDownloaded"] is NSNull)
        XCTAssertTrue(models?.first?["totalSize"] is NSNull)
        XCTAssertNil(snapshot.jsonObject(includeAppIcon: false)["appIconDataUrl"])
    }

    func testReadyAndNavigationFailureUseTheirDedicatedCallbacks() {
        let host = ModelDownloadMiniPanelWebView()
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
        let host = ModelDownloadMiniPanelWebView()
        host.resourcesURLProvider = { URL(fileURLWithPath: "/definitely-missing-model-download-assets") }
        var didFailNavigation = false
        host.onNavigationFailed = { didFailNavigation = true }

        host.loadContent(snapshot: ModelDownloadPanelSnapshot(
            phaseMessage: "Preparing...",
            isComplete: false,
            quantizedPercentage: 0,
            appIconDataUrl: nil,
            models: []
        ))

        XCTAssertTrue(didFailNavigation)
        host.tearDown()
    }
}
