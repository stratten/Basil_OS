import AppKit
import XCTest
@testable import BasilClient

final class AgentTaskCaptureDropTargetTests: XCTestCase {
    func testFileURLsReadsOnlyFileURLPasteboardObjects() {
        let pasteboard = NSPasteboard(name: NSPasteboard.Name("AgentTaskCaptureDropTargetTests-\(UUID().uuidString)"))
        let expectedURL = URL(fileURLWithPath: "/tmp/agent-task-reference.pdf")
        pasteboard.clearContents()
        XCTAssertTrue(pasteboard.writeObjects([expectedURL as NSURL]))

        XCTAssertEqual(DropTargetWebView.fileURLs(from: pasteboard), [expectedURL])
    }

    func testFileURLsRejectsPasteboardsWithoutFileURLs() {
        let pasteboard = NSPasteboard(name: NSPasteboard.Name("AgentTaskCaptureDropTargetTests-\(UUID().uuidString)"))
        pasteboard.clearContents()
        XCTAssertTrue(pasteboard.setString("plain text", forType: .string))

        XCTAssertEqual(DropTargetWebView.fileURLs(from: pasteboard), [])
    }
}
