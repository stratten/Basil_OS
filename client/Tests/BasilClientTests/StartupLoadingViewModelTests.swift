import XCTest
@testable import BasilClient

@MainActor
final class StartupLoadingViewModelTests: XCTestCase {
    func testAutomaticCompletionWaitsUntilDrawnInAndTheMinimumHold() async {
        let viewModel = StartupLoadingViewModel(minimumVisibleDuration: 0.05)
        var completed = false
        viewModel.onCompletion { completed = true }

        viewModel.complete()
        XCTAssertFalse(completed)

        viewModel.markDrawnIn()
        XCTAssertFalse(completed)

        try? await Task.sleep(nanoseconds: 80_000_000)
        XCTAssertTrue(completed)
    }

    func testImmediateCompletionDoesNotWaitForTheHold() {
        let viewModel = StartupLoadingViewModel(minimumVisibleDuration: 2)
        var completed = false
        viewModel.onCompletion { completed = true }

        viewModel.complete(immediately: true)

        XCTAssertTrue(completed)
    }

    private func startedViewModel() -> (StartupLoadingViewModel, Date) {
        let viewModel = StartupLoadingViewModel(minimumVisibleDuration: 0, slowStartLimitSeconds: 120, slowStartRecheckSeconds: 3600)
        let start = Date(timeIntervalSince1970: 1_000_000)
        viewModel.markStarted(at: start)
        return (viewModel, start)
    }

    func testTheFailsafeHidesTheWindowAtOnceWhenTheBackendAnsweredButNeverFinishedStarting() {
        let (viewModel, start) = startedViewModel()
        var completed = false
        viewModel.onCompletion { completed = true }
        viewModel.noteBackendReached()

        viewModel.evaluateFailsafe(now: start.addingTimeInterval(15))

        XCTAssertTrue(completed)
    }

    func testAPendingBackendKeepsTheWindowUpWithAStillStartingMessage() {
        let (viewModel, start) = startedViewModel()
        var completed = false
        var messages: [String] = []
        viewModel.onCompletion { completed = true }
        viewModel.onStatusChange { messages.append($0) }

        viewModel.evaluateFailsafe(now: start.addingTimeInterval(15))
        viewModel.evaluateFailsafe(now: start.addingTimeInterval(60))

        XCTAssertFalse(completed)
        XCTAssertEqual(viewModel.currentMessage, StartupLoadingViewModel.slowStartMessage)
        XCTAssertEqual(messages, [StartupLoadingViewModel.slowStartMessage], "The message is published once, not on every recheck")
    }

    func testABackendThatNeverAnswersIsHiddenAtTheLimit() {
        let (viewModel, start) = startedViewModel()
        var completed = false
        viewModel.onCompletion { completed = true }

        viewModel.evaluateFailsafe(now: start.addingTimeInterval(119))
        XCTAssertFalse(completed)

        viewModel.evaluateFailsafe(now: start.addingTimeInterval(120))
        XCTAssertTrue(completed)
    }

    func testABackendThatAnswersWhileTheWindowIsStillUpEndsTheWaitAtTheNextCheck() {
        let (viewModel, start) = startedViewModel()
        var completed = false
        viewModel.onCompletion { completed = true }

        viewModel.evaluateFailsafe(now: start.addingTimeInterval(20))
        XCTAssertFalse(completed)

        viewModel.noteBackendReached()
        viewModel.evaluateFailsafe(now: start.addingTimeInterval(25))
        XCTAssertTrue(completed)
    }

    func testTheFailsafeDoesNothingBeforeMonitoringStartsOrAfterItStops() {
        let viewModel = StartupLoadingViewModel(minimumVisibleDuration: 0)
        var completed = false
        viewModel.onCompletion { completed = true }

        viewModel.evaluateFailsafe(now: Date())
        XCTAssertFalse(completed, "Not started yet")

        viewModel.markStarted(at: Date(timeIntervalSince1970: 1))
        viewModel.stopMonitoring()
        viewModel.evaluateFailsafe(now: Date())
        XCTAssertFalse(completed, "Stopped")
    }
}
