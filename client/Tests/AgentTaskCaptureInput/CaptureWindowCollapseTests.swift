import XCTest
@testable import BasilClient

@MainActor
final class CaptureWindowCollapseTests: XCTestCase {
    private func makeController(frame: NSRect = NSRect(x: 100, y: 100, width: 520, height: 420)) -> (AgentTaskCaptureInputWindowController, NSWindow, AgentTaskCaptureViewModel) {
        let controller = AgentTaskCaptureInputWindowController()
        let window = NSWindow(contentRect: frame, styleMask: [.borderless, .resizable], backing: .buffered, defer: true)
        window.minSize = NSSize(width: 280, height: 235)
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.isTextEntryMode = true
        controller.panel = window
        controller.collapseController = WindowCollapseController(
            window: window,
            compactSize: AgentTaskCaptureInputWindowController.collapsedSize(headerExtent: AgentTaskCaptureInputWindowController.defaultHeaderExtent),
            fallbackExpandedSize: NSSize(width: 280, height: 235)
        )
        return (controller, window, viewModel)
    }

    /// The expand animates, so wait for the window to reach its target size instead of reading it mid-animation.
    private func waitForSize(_ window: NSWindow, _ size: NSSize, file: StaticString = #filePath, line: UInt = #line) {
        let reached = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                abs(window.frame.width - size.width) <= 1 && abs(window.frame.height - size.height) <= 1
            },
            object: nil
        )
        wait(for: [reached], timeout: 5)
        XCTAssertEqual(window.frame.size.width, size.width, accuracy: 1, file: file, line: line)
        XCTAssertEqual(window.frame.size.height, size.height, accuracy: 1, file: file, line: line)
    }

    func testCollapsedSizeIsNarrowerThanTextEntryAndFitsTheHeaderRow() {
        let size = AgentTaskCaptureInputWindowController.collapsedSize(headerExtent: 40)
        XCTAssertEqual(size.width, AgentTaskCaptureInputWindowController.collapsedWidth)
        XCTAssertLessThan(size.width, AgentTaskCaptureViewModel.CapturePanelLayout.textWidth)
        XCTAssertEqual(size.height, 40 + AgentTaskCaptureInputWindowController.collapsedBottomInset)
        XCTAssertGreaterThan(AgentTaskCaptureInputWindowController.collapsedSize(headerExtent: 0).height, 0)
    }

    func testCollapsingShrinksToTheHeaderAndExpandingRestoresTheExactSize() {
        let (controller, window, viewModel) = makeController()
        let before = window.frame

        controller.applyWindowCollapse(true, viewModel: viewModel)
        XCTAssertEqual(controller.collapseController?.isCollapsed, true)
        XCTAssertEqual(window.frame.height, AgentTaskCaptureInputWindowController.collapsedSize(headerExtent: controller.captureHeaderExtent).height, accuracy: 1)
        XCTAssertEqual(window.frame.width, AgentTaskCaptureInputWindowController.collapsedWidth, accuracy: 1)
        XCTAssertEqual(window.frame.maxY, before.maxY, accuracy: 1, "the top edge stays put")

        controller.applyWindowCollapse(false, viewModel: viewModel)
        XCTAssertEqual(controller.collapseController?.isCollapsed, false)
        waitForSize(window, before.size)
        XCTAssertEqual(window.frame.maxY, before.maxY, accuracy: 1)
    }

    func testVoiceModeNeverCollapses() {
        let (controller, window, viewModel) = makeController()
        viewModel.isTextEntryMode = false
        let before = window.frame

        controller.applyWindowCollapse(true, viewModel: viewModel)

        XCTAssertEqual(controller.collapseController?.isCollapsed, false)
        XCTAssertEqual(window.frame, before)
    }

    func testAnExpandAlwaysWorksEvenAfterTheModeLeftTextEntry() {
        let (controller, window, viewModel) = makeController()
        let before = window.frame
        controller.applyWindowCollapse(true, viewModel: viewModel)
        viewModel.isTextEntryMode = false

        controller.applyWindowCollapse(false, viewModel: viewModel)

        XCTAssertEqual(controller.collapseController?.isCollapsed, false)
        waitForSize(window, before.size)
    }

    func testRepeatedRequestsForTheSameStateAreNoOps() {
        let (controller, window, viewModel) = makeController()
        controller.applyWindowCollapse(false, viewModel: viewModel)
        XCTAssertEqual(window.frame.size, NSSize(width: 520, height: 420))
        controller.applyWindowCollapse(true, viewModel: viewModel)
        let collapsed = window.frame
        controller.applyWindowCollapse(true, viewModel: viewModel)
        XCTAssertEqual(window.frame, collapsed)
    }

    func testTheUsersChosenSizeSurvivesACollapseAndExpand() {
        let (controller, _, viewModel) = makeController()
        controller.userExpandedSizeValue = NSSize(width: 520, height: 420)

        controller.applyWindowCollapse(true, viewModel: viewModel)
        controller.userExpandedSizeValue = NSSize(width: 280, height: 44)
        controller.applyWindowCollapse(false, viewModel: viewModel)

        XCTAssertEqual(controller.userExpandedSizeValue, NSSize(width: 520, height: 420))
    }

    func testResizeNotificationsDuringATransitionAreNotTheUsersChoiceUntilTheTargetIsReached() {
        let (controller, _, _) = makeController()
        controller.collapseTransitionTargetSize = NSSize(width: 280, height: 44)

        XCTAssertTrue(controller.isCollapseTransitionResize(frameSize: NSSize(width: 400, height: 300)))
        XCTAssertNotNil(controller.collapseTransitionTargetSize)
        XCTAssertTrue(controller.isCollapseTransitionResize(frameSize: NSSize(width: 280, height: 44)))
        XCTAssertNil(controller.collapseTransitionTargetSize)
        XCTAssertFalse(controller.isCollapseTransitionResize(frameSize: NSSize(width: 300, height: 260)), "later resizes are the user's own")
    }

    func testWithoutATransitionNoResizeIsTreatedAsOurs() {
        let (controller, _, _) = makeController()
        XCTAssertFalse(controller.isCollapseTransitionResize(frameSize: NSSize(width: 280, height: 44)))
    }

    func testStartingALiveResizeEndsTransitionBookkeeping() {
        let (controller, _, _) = makeController()
        controller.collapseTransitionTargetSize = NSSize(width: 280, height: 44)
        controller.windowWillStartLiveResize(Notification(name: NSWindow.willStartLiveResizeNotification))
        XCTAssertNil(controller.collapseTransitionTargetSize)
    }
}
