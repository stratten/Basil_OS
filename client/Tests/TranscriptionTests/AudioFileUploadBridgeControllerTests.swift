import XCTest
@testable import BasilClient

@MainActor
final class AudioFileUploadBridgeControllerTests: XCTestCase {
    private final class MockOutput: AudioFileUploadBridgeOutput {
        var snapshots: [(revision: Int, payload: [String: Any])] = []

        func sendInit(theme: [String: Any]) {}

        func sendSnapshot(revision: Int, payload: [String: Any]) {
            snapshots.append((revision, payload))
        }

        func sendDelta(revision: Int, payload: [String: Any]) {}
    }

    func testInitialSnapshotIncludesEmptyFormState() {
        let viewModel = AudioFileUploadViewModel()
        let output = MockOutput()
        let window = NSWindow()
        let collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 600, height: 64),
            fallbackExpandedSize: NSSize(width: 600, height: 560)
        )
        let bridge = AudioFileUploadBridgeController(viewModel: viewModel, output: output, window: window, collapseController: collapseController)

        bridge.sendInitialSnapshot()

        XCTAssertEqual(output.snapshots.count, 1)
        XCTAssertEqual(output.snapshots.first?.payload["hasSelectedFile"] as? Bool, false)
        XCTAssertEqual(output.snapshots.first?.payload["canUpload"] as? Bool, false)
        XCTAssertEqual(output.snapshots.first?.payload["selectedLanguage"] as? String, "auto")
    }

    func testDismissErrorIntentClearsTheErrorState() {
        let viewModel = AudioFileUploadViewModel()
        viewModel.showError = true
        viewModel.errorMessage = "Failed to upload file"
        let output = MockOutput()
        let window = NSWindow()
        let collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 600, height: 64),
            fallbackExpandedSize: NSSize(width: 600, height: 560)
        )
        let bridge = AudioFileUploadBridgeController(viewModel: viewModel, output: output, window: window, collapseController: collapseController)

        bridge.handle(intent: ["type": "dismissError"])

        XCTAssertFalse(viewModel.showError)
        XCTAssertEqual(viewModel.errorMessage, "")
    }

    func testCopyTranscriptionResultAppliesCachedTextReplacementRules() {
        let previousCache = APIClient.shared.getCachedTranscriptionSettings()
        APIClient.shared.cacheTranscriptionSettings(
            previousCache.applying(
                textReplacements: [
                    TranscriptionTextReplacementRule(source: "slash", replacement: "/"),
                ]
            )
        )
        defer {
            APIClient.shared.cacheTranscriptionSettings(previousCache)
        }

        let viewModel = AudioFileUploadViewModel()
        viewModel.transcriptionResult = "go slash home"
        let output = MockOutput()
        let window = NSWindow()
        let collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 600, height: 64),
            fallbackExpandedSize: NSSize(width: 600, height: 560)
        )
        let bridge = AudioFileUploadBridgeController(
            viewModel: viewModel,
            output: output,
            window: window,
            collapseController: collapseController
        )

        bridge.handle(intent: ["type": "copyTranscriptionResult"])

        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "go / home")
        XCTAssertEqual(viewModel.transcriptionResult, "go slash home")
    }
}
