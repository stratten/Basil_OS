import AppKit
import Darwin
import PDFKit
import XCTest
@testable import BasilClient

@MainActor
private final class FileObservationRecorder {
    let firstChange: XCTestExpectation
    let noSecondChange: XCTestExpectation
    private(set) var observedChangeCount = 0

    init(testCase: XCTestCase) {
        firstChange = testCase.expectation(description: "observes first file replacement")
        noSecondChange = testCase.expectation(description: "does not observe writes after invalidation")
        noSecondChange.isInverted = true
    }

    func recordChange() {
        observedChangeCount += 1
        if observedChangeCount == 1 {
            firstChange.fulfill()
        } else {
            noSecondChange.fulfill()
        }
    }
}

final class AgentTaskNativePreviewTests: XCTestCase {
    func testClippedFrameReturnsTheVisibleIntersection() {
        let frame = AgentTaskNativePreviewFrame(x: 350, y: 240, width: 100, height: 100)

        XCTAssertEqual(
            frame.clipped(to: NSRect(x: 0, y: 0, width: 400, height: 300)),
            NSRect(x: 350, y: 240, width: 50, height: 60)
        )
    }

    func testClippedFrameRejectsFullyOffscreenAndZeroAreaFrames() {
        let bounds = NSRect(x: 0, y: 0, width: 400, height: 300)

        XCTAssertNil(AgentTaskNativePreviewFrame(x: 401, y: 0, width: 10, height: 10).clipped(to: bounds))
        XCTAssertNil(AgentTaskNativePreviewFrame(x: 0, y: 0, width: 0, height: 10).clipped(to: bounds))
        XCTAssertNil(AgentTaskNativePreviewFrame(x: 0, y: 0, width: 10, height: 0).clipped(to: bounds))
    }

    func testLocalPreviewNavigationPolicyIsScopedToLoopbackAndLocalSchemes() {
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "file:///private/report.html")!, mode: "static"))
        XCTAssertTrue(allowsLocalPreviewNavigation(URL(string: "basil-preview-file://preview/report.html")!, mode: "static"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "https://example.com")!, mode: "static"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "basil-preview-file://preview/report.html")!, mode: "devServer"))

        XCTAssertTrue(allowsLocalPreviewNavigation(URL(string: "http://127.0.0.1:4173/dashboard")!, mode: "devServer"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "http://localhost:4173")!, mode: "devServer"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "http://0.0.0.0:4173")!, mode: "devServer"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "https://127.0.0.1:4173")!, mode: "devServer"))
        XCTAssertFalse(allowsLocalPreviewNavigation(URL(string: "myapp://deep-link")!, mode: "devServer"))
    }

    func testInlinePreviewGeometryMapsCSSTopLeftSlotToNativeFrame() {
        let frame = AgentTaskNativePreviewGeometry.convertInlinePreviewFrame(
            left: 650,
            top: 120,
            width: 300,
            height: 280,
            viewportWidth: 1000,
            viewportHeight: 700,
            hostBounds: NSRect(x: 0, y: 0, width: 1000, height: 700),
            hostIsFlipped: false
        )

        XCTAssertEqual(frame, AgentTaskNativePreviewFrame(x: 650, y: 300, width: 300, height: 280))
    }

    func testInlinePreviewGeometryKeepsCSSTopCoordinateForAFlippedHost() {
        let frame = AgentTaskNativePreviewGeometry.convertInlinePreviewFrame(
            left: 650,
            top: 120,
            width: 300,
            height: 280,
            viewportWidth: 1000,
            viewportHeight: 700,
            hostBounds: NSRect(x: 0, y: 0, width: 1000, height: 700),
            hostIsFlipped: true
        )

        XCTAssertEqual(frame, AgentTaskNativePreviewFrame(x: 650, y: 120, width: 300, height: 280))
    }

    func testFilePreviewWindowFrameReservesChromeForBothCoordinateSystems() {
        let bounds = NSRect(x: 0, y: 0, width: 1000, height: 700)

        XCTAssertEqual(
            AgentTaskNativePreviewGeometry.filePreviewWindowFrame(
                hostBounds: bounds,
                chromeHeight: 86,
                inset: 3,
                hostIsFlipped: false
            ),
            AgentTaskNativePreviewFrame(x: 3, y: 3, width: 994, height: 611)
        )
        XCTAssertEqual(
            AgentTaskNativePreviewGeometry.filePreviewWindowFrame(
                hostBounds: bounds,
                chromeHeight: 86,
                inset: 3,
                hostIsFlipped: true
            ),
            AgentTaskNativePreviewFrame(x: 3, y: 86, width: 994, height: 611)
        )
    }

    @MainActor
    func testOverlayPresentationKeepsMountedViewFrameEqualToClippedRequest() {
        let host = NSView(frame: NSRect(x: 0, y: 0, width: 1000, height: 700))
        let overlay = AgentTaskNativePreviewOverlay(hostView: host)
        let previewView = NSView(frame: .zero)
        let requested = AgentTaskNativePreviewFrame(x: 650, y: 300, width: 300, height: 280)

        overlay.present(previewView, frame: requested)

        XCTAssertEqual(previewView.frame, NSRect(x: 650, y: 300, width: 300, height: 280))
        XCTAssertFalse(previewView.isHidden)

        overlay.update(frame: AgentTaskNativePreviewFrame(x: 640, y: 280, width: 320, height: 300))
        XCTAssertEqual(previewView.frame, NSRect(x: 640, y: 280, width: 320, height: 300))
    }

    @MainActor
    func testPDFLoaderAcceptsAValidTemporaryPDF() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("preview.pdf")

        try writeOnePagePDF(to: url)

        let document = AgentTaskNativePDFPreview.loadDocument(at: url)
        XCTAssertEqual(document?.pageCount, 1)
    }

    func testPDFLoaderRejectsTextAtAPDFPath() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("not-a-pdf.pdf")

        try Data("not a portable document".utf8).write(to: url)

        XCTAssertNil(AgentTaskNativePDFPreview.loadDocument(at: url))
    }

    @MainActor
    func testFileRevisionAndOverlayReplacementTrackAValidNewPDF() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("preview.pdf")
        try writeOnePagePDF(to: url)
        let initialRevision = try XCTUnwrap(AgentTaskPreviewFileRevision(url: url))
        let initialDocument = try XCTUnwrap(AgentTaskNativePDFPreview.loadDocument(at: url))

        try writeTwoPagePDF(to: url)
        let replacementRevision = try XCTUnwrap(AgentTaskPreviewFileRevision(url: url))
        let replacementDocument = try XCTUnwrap(AgentTaskNativePDFPreview.loadDocument(at: url))
        XCTAssertNotEqual(initialRevision, replacementRevision)

        let host = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 300))
        let overlay = AgentTaskNativePreviewOverlay(hostView: host)
        defer { overlay.hide() }
        let initialView = AgentTaskNativePDFPreview.makeView(document: initialDocument)
        overlay.present(initialView, frame: AgentTaskNativePreviewFrame(x: 0, y: 0, width: 300, height: 300))
        overlay.replaceDocument(replacementDocument)

        XCTAssertEqual((overlay.currentView as? PDFView)?.document?.pageCount, 2)
    }

    @MainActor
    func testFileObserverStopsAfterInvalidation() async throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("preview.pdf")
        try writeOnePagePDF(to: url)

        let recorder = FileObservationRecorder(testCase: self)
        let observer = try XCTUnwrap(AgentTaskPreviewFileObserver(url: url) {
            recorder.recordChange()
        })

        try replacePDF(at: url, pageCount: 2)
        await fulfillment(of: [recorder.firstChange], timeout: 2)
        observer.invalidate()
        try replacePDF(at: url, pageCount: 1)
        await fulfillment(of: [recorder.noSecondChange], timeout: 0.2)
        XCTAssertEqual(recorder.observedChangeCount, 1)
    }

    @MainActor
    func testPDFViewFactoryCreatesIndependentConfiguredViews() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("preview.pdf")
        try writeOnePagePDF(to: url)
        let document = try XCTUnwrap(AgentTaskNativePDFPreview.loadDocument(at: url))

        let first = AgentTaskNativePDFPreview.makeView(document: document)
        let second = AgentTaskNativePDFPreview.makeView(document: document)

        XCTAssertFalse(first === second)
        XCTAssertTrue(first.autoScales)
        XCTAssertEqual(first.displayMode, .singlePageContinuous)
        XCTAssertEqual(first.displayDirection, .vertical)
        XCTAssertTrue(second.autoScales)
        XCTAssertEqual(second.displayMode, .singlePageContinuous)
        XCTAssertEqual(second.displayDirection, .vertical)
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("AgentTaskNativePreviewTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func writeOnePagePDF(to url: URL) throws {
        try writePDF(to: url, pageCount: 1)
    }

    private func writeTwoPagePDF(to url: URL) throws {
        try writePDF(to: url, pageCount: 2)
    }

    private func replacePDF(at url: URL, pageCount: Int) throws {
        let replacementURL = url.deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("\(UUID().uuidString).pdf")
        defer { try? FileManager.default.removeItem(at: replacementURL) }
        try writePDF(to: replacementURL, pageCount: pageCount)
        guard rename(replacementURL.path, url.path) == 0 else {
            throw NSError(domain: "AgentTaskNativePreviewTests", code: Int(errno))
        }
    }

    private func writePDF(to url: URL, pageCount: Int) throws {
        var mediaBox = CGRect(x: 0, y: 0, width: 72, height: 72)
        guard let context = CGContext(url as CFURL, mediaBox: &mediaBox, nil) else {
            throw NSError(domain: "AgentTaskNativePreviewTests", code: 1)
        }
        for page in 0..<pageCount {
            context.beginPDFPage(nil)
            context.setFillColor(page.isMultiple(of: 2) ? NSColor.black.cgColor : NSColor.blue.cgColor)
            context.fill(CGRect(x: 12, y: 12, width: 48, height: 48))
            context.endPDFPage()
        }
        context.closePDF()
    }
}
