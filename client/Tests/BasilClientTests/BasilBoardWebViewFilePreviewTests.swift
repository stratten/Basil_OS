import XCTest
@testable import BasilClient

@MainActor
final class BasilBoardWebViewFilePreviewTests: XCTestCase {
    override func tearDown() {
        AgentTaskResultPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testPreviewFileRejectsRelativePathWithoutActivatingAgentTasksSurface() {
        let webView = BasilBoardWebView(entryPage: .conversation)

        webView.handleMessage(
            name: "basilBoardBridge",
            body: [
                "type": "previewFile",
                "requestId": "req-relative",
                "path": "artifact.txt",
            ]
        )

        XCTAssertNil(AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost)
        XCTAssertFalse(AgentTaskResultPresentationCoordinator.shared.isBoardVisible)
    }

    func testPreviewFileHandlesMissingAbsolutePathWithoutCrashing() {
        let webView = BasilBoardWebView(entryPage: .conversation)

        webView.handleMessage(
            name: "basilBoardBridge",
            body: [
                "type": "previewFile",
                "requestId": "req-missing",
                "path": "/tmp/basil-board-preview-missing-\(UUID().uuidString).md",
            ]
        )
    }

    func testPreviewFileHandlesExistingAbsolutePathWithoutCrashing() throws {
        let webView = BasilBoardWebView(entryPage: .conversation)
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("basil-board-preview-\(UUID().uuidString).md")
        try "# Preview\n".write(to: tempURL, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: tempURL) }

        webView.handleMessage(
            name: "basilBoardBridge",
            body: [
                "type": "previewFile",
                "requestId": "req-existing",
                "path": tempURL.path,
            ]
        )
    }

    func testCheckFilePreviewAvailabilityOmitsMissingPathsWithoutCrashing() throws {
        let webView = BasilBoardWebView(entryPage: .conversation)
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("basil-board-availability-\(UUID().uuidString).md")
        try "# Available\n".write(to: tempURL, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: tempURL) }

        webView.handleMessage(
            name: "basilBoardBridge",
            body: [
                "type": "checkFilePreviewAvailability",
                "requestId": "availability-req",
                "paths": [
                    tempURL.path,
                    "/tmp/basil-board-preview-deleted-\(UUID().uuidString).md",
                ],
            ]
        )
    }

    func testOpenFileRejectsRelativePathWithoutCrashing() {
        let webView = BasilBoardWebView(entryPage: .conversation)

        webView.handleMessage(
            name: "basilBoardBridge",
            body: [
                "type": "openFile",
                "path": "artifact.txt",
            ]
        )
    }

    func testPickTodoReferenceFilesBridgeMessageDoesNotCrash() {
        let webView = BasilBoardWebView(entryPage: .conversation)

        webView.handleMessage(
            name: "basilBoardBridge",
            body: ["type": "pickTodoReferenceFiles"]
        )
    }

    func testUnknownBridgeTypeDoesNotCrash() {
        let webView = BasilBoardWebView(entryPage: .conversation)

        webView.handleMessage(
            name: "basilBoardBridge",
            body: ["type": "notARealPreviewBridgeType"]
        )
    }
}
