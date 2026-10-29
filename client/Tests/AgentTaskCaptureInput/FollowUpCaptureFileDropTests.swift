import XCTest
@testable import BasilClient

@MainActor
final class FollowUpCaptureFileDropTests: XCTestCase {
    private var resultHost: AgentTaskResultWebView!
    private var scratchDirectory: URL!

    override func setUp() async throws {
        resultHost = AgentTaskResultWebView()
        scratchDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("follow-up-drop-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratchDirectory, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        resultHost.tearDown()
        resultHost = nil
        try? FileManager.default.removeItem(at: scratchDirectory)
    }

    private func makeFile(named name: String) throws -> String {
        let url = scratchDirectory.appendingPathComponent(name)
        try Data("fixture".utf8).write(to: url)
        return url.path
    }

    private func recordingCapture() -> AgentTaskCaptureViewModel {
        let capture = AgentTaskCaptureViewModel(rootTaskId: "root", previousTaskId: "root")
        capture.isCapturing = true
        return capture
    }

    func testDropDuringARecordingAttachesToTheRecordingInsteadOfTheWebLayer() throws {
        let capture = recordingCapture()
        resultHost.routeFileDropsToFollowUpCapture { capture }
        let path = try makeFile(named: "report.pdf")

        XCTAssertEqual(resultHost.followUpCaptureDropSink?([path]), true)
        XCTAssertEqual(capture.referencePaths.map(\.path), [path])
    }

    func testTheWindowsNativeDropCallbackOffersTheFilesToTheRecordingFirst() throws {
        let capture = recordingCapture()
        resultHost.routeFileDropsToFollowUpCapture { capture }
        let path = try makeFile(named: "report.pdf")
        let nativeDrop = try XCTUnwrap((resultHost.webView as? FirstClickWebView)?.onFilesDropped)

        nativeDrop([path])

        XCTAssertEqual(capture.referencePaths.map(\.path), [path])
    }

    func testDropWithNoRecordingFallsThroughToTheTextFollowUp() throws {
        resultHost.routeFileDropsToFollowUpCapture { nil }
        let path = try makeFile(named: "report.pdf")

        XCTAssertEqual(resultHost.followUpCaptureDropSink?([path]), false)
    }

    func testDropAfterTheRecordingStoppedOrCompletedFallsThrough() throws {
        let capture = recordingCapture()
        resultHost.routeFileDropsToFollowUpCapture { capture }
        let path = try makeFile(named: "report.pdf")

        capture.isCapturing = false
        XCTAssertEqual(resultHost.followUpCaptureDropSink?([path]), false)

        capture.isCapturing = true
        capture.hasCompleted = true
        XCTAssertEqual(resultHost.followUpCaptureDropSink?([path]), false)
        XCTAssertTrue(capture.referencePaths.isEmpty)
    }

    func testRepeatedAndMissingPathsAreNotAddedTwice() throws {
        let capture = recordingCapture()
        resultHost.routeFileDropsToFollowUpCapture { capture }
        let path = try makeFile(named: "report.pdf")

        _ = resultHost.followUpCaptureDropSink?([path])
        _ = resultHost.followUpCaptureDropSink?([path, scratchDirectory.appendingPathComponent("missing.txt").path])
        XCTAssertEqual(capture.referencePaths.map(\.path), [path])
    }

    func testRemovingAReferenceByIndexOnlyAffectsAnActiveRecording() throws {
        let capture = recordingCapture()
        resultHost.routeFileDropsToFollowUpCapture { capture }
        let first = try makeFile(named: "a.txt")
        let second = try makeFile(named: "b.txt")
        _ = resultHost.followUpCaptureDropSink?([first, second])
        XCTAssertEqual(capture.referencePaths.count, 2)

        resultHost.onRemoveFollowUpCaptureReference?(0)
        XCTAssertEqual(capture.referencePaths.map(\.path), [second])

        resultHost.onRemoveFollowUpCaptureReference?(5)
        XCTAssertEqual(capture.referencePaths.map(\.path), [second])

        capture.isCapturing = false
        resultHost.onRemoveFollowUpCaptureReference?(0)
        XCTAssertEqual(capture.referencePaths.map(\.path), [second])
    }
}
