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
}
