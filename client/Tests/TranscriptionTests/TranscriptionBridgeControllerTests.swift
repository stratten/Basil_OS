import XCTest
@testable import BasilClient

@MainActor
final class TranscriptionBridgeControllerTests: XCTestCase {
    private final class MockOutput: TranscriptionBridgeOutput {
        var initThemes: [[String: Any]] = []
        var snapshots: [(revision: Int, payload: [String: Any])] = []
        var deltas: [(revision: Int, payload: [String: Any])] = []
        var meters: [Float] = []
        var shownModelPicker: (models: [TranscriptionModelOption], selectedModelId: String, anchorRect: [String: CGFloat])?

        func sendInit(theme: [String: Any]) {
            initThemes.append(theme)
        }

        func sendThemeChanged(theme: [String: Any]) {}

        func sendSnapshot(revision: Int, payload: [String: Any]) {
            snapshots.append((revision, payload))
        }

        func sendDelta(revision: Int, payload: [String: Any]) {
            deltas.append((revision, payload))
        }

        func sendMeter(audioLevel: Float) {
            meters.append(audioLevel)
        }

        func showTranscriptionModelPicker(
            models: [TranscriptionModelOption],
            selectedModelId: String,
            anchorRect: [String: CGFloat],
            onSelection: @escaping (String) -> Void
        ) {
            shownModelPicker = (models, selectedModelId, anchorRect)
        }
    }

    func testSendInitialSnapshotEmitsInitAndRevisionedSnapshot() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.isConnected = true
        viewModel.isModelReady = true
        viewModel.transcriptionText = "Ready to record"
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)

        bridge.sendInitialSnapshot()

        XCTAssertEqual(output.initThemes.count, 1)
        XCTAssertNotNil(output.initThemes.first?["primary"] as? String)
        XCTAssertEqual(output.snapshots.count, 1)
        XCTAssertEqual(output.snapshots.first?.revision, 1)
        XCTAssertEqual(output.snapshots.first?.payload["transcriptionText"] as? String, "Ready to record")
        XCTAssertEqual(output.snapshots.first?.payload["isConnected"] as? Bool, true)
        XCTAssertEqual(output.snapshots.first?.payload["bubbleMode"] as? String, "ambient")
        XCTAssertEqual(output.deltas.count, 0)
    }

    func testSubsequentViewModelChangeEmitsMonotonicDelta() async {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.transcriptionText = "Ready to record"
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)
        bridge.sendInitialSnapshot()

        viewModel.transcriptionText = "hello world"
        try? await Task.sleep(nanoseconds: 80_000_000)

        XCTAssertEqual(output.snapshots.count, 1)
        XCTAssertGreaterThanOrEqual(output.deltas.count, 1)
        XCTAssertEqual(output.deltas.last?.payload["transcriptionText"] as? String, "hello world")
        XCTAssertGreaterThan(output.deltas.last?.revision ?? 0, output.snapshots.first?.revision ?? 0)
    }

    func testClearAndCopyIntentsDispatchToViewModel() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.transcriptionText = "hello world"
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)

        bridge.handle(intent: ["type": "copyToClipboard"])
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "hello world ")

        bridge.handle(intent: ["type": "clearTranscription"])
        XCTAssertEqual(viewModel.transcriptionText, "Ready to record")
    }

    func testCopyIntentAppliesCachedTextReplacementRules() {
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

        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.transcriptionText = "go slash home"
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)

        bridge.handle(intent: ["type": "copyToClipboard"])

        XCTAssertEqual(NSPasteboard.general.string(forType: .string), "go / home ")
        XCTAssertEqual(viewModel.transcriptionText, "go slash home")
    }

    func testToggleMinimizedIntentFlipsViewModelState() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.isMinimized = false
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)

        bridge.handle(intent: ["type": "toggleMinimizedState"])
        XCTAssertTrue(viewModel.isMinimized)
    }

    func testRequestResizeIsANoOp() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)
        bridge.sendInitialSnapshot()
        let snapshotCount = output.snapshots.count
        let deltaCount = output.deltas.count

        bridge.handle(intent: ["type": "requestResize", "width": 400, "height": 300])

        XCTAssertEqual(output.snapshots.count, snapshotCount)
        XCTAssertEqual(output.deltas.count, deltaCount)
    }

    func testShowErrorPopoverIntentUsesCurrentViewModelError() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        let output = MockOutput()
        var shownMessage: String?
        let bridge = TranscriptionBridgeController(
            viewModel: viewModel,
            output: output,
            showErrorPopover: { shownMessage = $0 }
        )

        bridge.handle(intent: ["type": "showErrorPopover"])
        XCTAssertNil(shownMessage)

        viewModel.error = "Microphone access denied"
        bridge.handle(intent: ["type": "showErrorPopover"])

        XCTAssertEqual(shownMessage, "Microphone access denied")
    }

    func testShowTranscriptionModelMenuUsesNativePickerAnchoredToTheChevron() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.availableTranscriptionModels = [
            TranscriptionModelOption(id: "local", displayName: "Local Model", isApiModel: false, provider: nil),
        ]
        viewModel.currentTranscriptionModelId = "local"
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)

        bridge.handle(intent: [
            "type": "showTranscriptionModelMenu",
            "anchorRect": ["x": 12, "y": 18, "width": 14, "height": 14],
        ])

        XCTAssertEqual(output.shownModelPicker?.models.map(\.id), ["local"])
        XCTAssertEqual(output.shownModelPicker?.selectedModelId, "local")
        XCTAssertEqual(output.shownModelPicker?.anchorRect, ["x": 12, "y": 18, "width": 14, "height": 14])
    }

    func testThemeSnapshotContainsRequiredTokens() {
        let theme = TranscriptionThemeSnapshot.currentJSON()
        for key in ["primary", "secondary", "backgroundPrimary", "textPrimary", "textSecondary", "recordingBase", "errorBase", "warningBase", "preferredFontName"] {
            XCTAssertNotNil(theme[key], "Missing transcription theme token: \(key)")
        }
    }

    func testAudioLevelUpdatesDoNotProduceSnapshotOrDeltaEvents() async {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        let output = MockOutput()
        let bridge = TranscriptionBridgeController(viewModel: viewModel, output: output)
        bridge.sendInitialSnapshot()
        let snapshotCount = output.snapshots.count
        let deltaCount = output.deltas.count

        viewModel.updateAudioLevel(0.42)
        try? await Task.sleep(nanoseconds: 60_000_000)

        XCTAssertEqual(output.snapshots.count, snapshotCount)
        XCTAssertEqual(output.deltas.count, deltaCount)
        XCTAssertEqual(output.meters.last, 0.42)
    }

    func testUpdateAudioLevelClampsValues() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)

        viewModel.updateAudioLevel(4.0)
        XCTAssertEqual(viewModel.audioLevel, 1.0)

        viewModel.updateAudioLevel(-2.0)
        XCTAssertEqual(viewModel.audioLevel, 0.0)
    }
}
