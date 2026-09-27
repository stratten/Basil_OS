import XCTest
@testable import BasilClient

final class CaptureSnapshotMappingTests: XCTestCase {
    private var tempDirectoryURL: URL!
    private var tempFileURL: URL!

    override func setUpWithError() throws {
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("CaptureSnapshotMappingTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        tempDirectoryURL = tempDir

        let fileURL = tempDir.appendingPathComponent("report.pdf")
        FileManager.default.createFile(atPath: fileURL.path, contents: Data("test".utf8))
        tempFileURL = fileURL
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: tempDirectoryURL)
    }

    @MainActor
    func testReferencePathsMapDirectoryAndFileFlagsIndependently() {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.referencePaths = [tempDirectoryURL, tempFileURL]

        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 1)

        XCTAssertEqual(snapshot.referencePaths.count, 2)
        XCTAssertEqual(snapshot.referencePaths[0].path, tempDirectoryURL.path)
        XCTAssertTrue(snapshot.referencePaths[0].isDirectory)
        XCTAssertEqual(snapshot.referencePaths[1].path, tempFileURL.path)
        XCTAssertFalse(snapshot.referencePaths[1].isDirectory)
    }

    @MainActor
    func testReferencePathsForNonexistentPathDefaultToNonDirectory() {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.referencePaths = [URL(fileURLWithPath: "/nonexistent/path/does-not-exist")]

        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 1)

        XCTAssertEqual(snapshot.referencePaths.count, 1)
        XCTAssertFalse(snapshot.referencePaths[0].isDirectory)
    }

    @MainActor
    func testJsonObjectRoundTripsReferencePathsAsArrayOfDictionaries() throws {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.referencePaths = [tempFileURL]
        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 7)

        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let referencePaths = decoded?["referencePaths"] as? [[String: Any]]

        XCTAssertEqual(referencePaths?.count, 1)
        XCTAssertEqual(referencePaths?[0]["path"] as? String, tempFileURL.path)
        XCTAssertEqual(referencePaths?[0]["isDirectory"] as? Bool, false)
    }

    @MainActor
    func testIsDraggingOverIsSourcedFromTheWindowControllerFlagNotTheViewModel() throws {
        let viewModel = AgentTaskCaptureViewModel()
        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: true, revision: 1)

        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(decoded?["isDraggingOver"] as? Bool, true)
    }

    @MainActor
    func testRevisionIsEchoedVerbatimIntoJsonObject() throws {
        let viewModel = AgentTaskCaptureViewModel()
        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 42)

        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(decoded?["revision"] as? Int, 42)
    }

    @MainActor
    func testSelectedModelIsMappedIntoSnapshotAndJsonObject() throws {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.selectedAgentTaskModelId = "reasoning-model-123"

        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 1)
        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(snapshot.selectedModelId, "reasoning-model-123")
        XCTAssertEqual(decoded?["selectedModelId"] as? String, "reasoning-model-123")
    }

    @MainActor
    func testFallbackCaptureStateMapsTimerAndConfiguredHotkeyFields() throws {
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.useIntelligentCapture = false
        viewModel.progressPercentage = 0.4
        viewModel.remainingSeconds = 4

        let snapshot = CaptureSnapshot.from(viewModel: viewModel, isDraggingOver: false, revision: 1)
        let data = try JSONSerialization.data(withJSONObject: snapshot.jsonObject)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(decoded?["useIntelligentCapture"] as? Bool, false)
        XCTAssertEqual(decoded?["progressPercentage"] as? Double ?? -1, 0.4, accuracy: 0.0001)
        XCTAssertEqual(decoded?["remainingSeconds"] as? Int, 4)
        XCTAssertTrue(decoded?["agentTaskHotkeyDisplay"] is String || decoded?["agentTaskHotkeyDisplay"] is NSNull)
    }
}
