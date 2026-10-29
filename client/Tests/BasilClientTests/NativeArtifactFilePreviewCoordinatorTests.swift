import AppKit
import PDFKit
import XCTest
@testable import BasilClient

@MainActor
final class NativeArtifactFilePreviewCoordinatorTests: XCTestCase {
    func testReportsMissingDirectoryUnsupportedAndOversizedFiles() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let unsupportedURL = directory.appendingPathComponent("report.bin")
        let oversizedURL = directory.appendingPathComponent("large.md")
        try Data([0xFF]).write(to: unsupportedURL)
        try Data(repeating: 0x61, count: 1_000_001).write(to: oversizedURL)

        var payloads: [[String: Any]] = []
        let coordinator = makeCoordinator(
            host: NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 300))
        ) { _, payload in
            payloads.append(payload)
        }

        coordinator.handleFilePreviewRequest(requestId: "missing", path: directory.appendingPathComponent("missing.md").path)
        coordinator.handleFilePreviewRequest(requestId: "directory", path: directory.path)
        coordinator.handleFilePreviewRequest(requestId: "unsupported", path: unsupportedURL.path)
        coordinator.handleFilePreviewRequest(requestId: "oversized", path: oversizedURL.path)
        coordinator.rejectFilePreviewRequest(requestId: "invalid-path", path: "report.md")

        XCTAssertEqual(payloads.map { $0["requestId"] as? String }, ["missing", "directory", "unsupported", "oversized", "invalid-path"])
        XCTAssertEqual(payloads.map { $0["kind"] as? String }, ["unsupported", "unsupported", "unsupported", "unsupported", "unsupported"])
        XCTAssertEqual(payloads[0]["error"] as? String, "The file could not be found.")
        XCTAssertEqual(payloads[1]["error"] as? String, "Folders cannot be previewed here.")
        XCTAssertEqual(payloads[2]["error"] as? String, "The file could not be read as UTF-8 text.")
        XCTAssertEqual(payloads[3]["error"] as? String, "This file is too large to preview in the widget.")
        XCTAssertEqual(payloads[4]["error"] as? String, "The file path is invalid.")
    }

    func testFallsBackToTextPreviewForUnknownUTF8Extension() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("automation.applescript")
        let source = "on run\n    return \"Hello from AppleScript\"\nend run\n"
        try source.write(to: url, atomically: true, encoding: .utf8)

        var readyPayload: [String: Any]?
        let coordinator = makeCoordinator(
            host: NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 300))
        ) { callback, payload in
            if callback == "onFilePreviewReady" {
                readyPayload = payload
            }
        }

        coordinator.handleFilePreviewRequest(requestId: "applescript", path: url.path)

        XCTAssertEqual(readyPayload?["kind"] as? String, "text")
        XCTAssertEqual(readyPayload?["content"] as? String, source)
        XCTAssertNil(readyPayload?["error"])
    }

    func testReadsTextAndPublishesLiveFileUpdates() async throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("report.md")
        try "first version".write(to: url, atomically: true, encoding: .utf8)

        let updated = expectation(description: "publishes text update")
        var readyPayload: [String: Any]?
        var updatePayload: [String: Any]?
        let coordinator = makeCoordinator(
            host: NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 300))
        ) { callback, payload in
            if callback == "onFilePreviewReady" {
                readyPayload = payload
            } else if callback == "onFilePreviewUpdated" {
                updatePayload = payload
                updated.fulfill()
            }
        }

        coordinator.handleFilePreviewRequest(requestId: "text", path: url.path)
        XCTAssertEqual(readyPayload?["content"] as? String, "first version")

        try "second version with a different byte count".write(to: url, atomically: true, encoding: .utf8)
        await fulfillment(of: [updated], timeout: 2)

        XCTAssertEqual(updatePayload?["requestId"] as? String, "text")
        XCTAssertEqual(updatePayload?["content"] as? String, "second version with a different byte count")
    }

    func testReplacementDropsStalePdfRequestAndClearsTheActiveOverlay() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let firstURL = directory.appendingPathComponent("first.pdf")
        let secondURL = directory.appendingPathComponent("second.pdf")
        try writePDF(to: firstURL)
        try writePDF(to: secondURL)

        let host = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 300))
        let coordinator = makeCoordinator(host: host) { _, _ in }
        let frame = AgentTaskNativePreviewFrame(x: 0, y: 0, width: 300, height: 300)

        coordinator.handleFilePreviewRequest(requestId: "first", path: firstURL.path)
        coordinator.handleFilePreviewRequest(requestId: "second", path: secondURL.path)
        coordinator.presentInlinePDFPreview(requestId: "first", frame: frame)
        XCTAssertTrue(host.subviews.isEmpty)

        coordinator.presentInlinePDFPreview(requestId: "second", frame: frame)
        XCTAssertEqual(host.subviews.count, 1)

        coordinator.clearActiveFilePreview(requestId: "second")
        XCTAssertTrue(host.subviews.isEmpty)
    }

    private func makeCoordinator(
        host: NSView,
        emit: @escaping (_ callback: String, _ payload: [String: Any]) -> Void
    ) -> NativeArtifactFilePreviewCoordinator {
        NativeArtifactFilePreviewCoordinator(emit: emit, hostView: { host })
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("NativeArtifactFilePreviewCoordinatorTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func writePDF(to url: URL) throws {
        var mediaBox = CGRect(x: 0, y: 0, width: 72, height: 72)
        guard let context = CGContext(url as CFURL, mediaBox: &mediaBox, nil) else {
            throw NSError(domain: "NativeArtifactFilePreviewCoordinatorTests", code: 1)
        }
        context.beginPDFPage(nil)
        context.setFillColor(NSColor.black.cgColor)
        context.fill(CGRect(x: 12, y: 12, width: 48, height: 48))
        context.endPDFPage()
        context.closePDF()
    }
}
