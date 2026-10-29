import XCTest
@testable import BasilClient

final class WindowCaptureProcessRunnerTests: XCTestCase {
    func testClassifyTrimsSuccessfulOutput() {
        let outcome = WindowCaptureProcessRunner.classify(
            terminationStatus: 0,
            standardOutput: "Safari|Example|com.apple.Safari|/tmp/a.png\n",
            standardError: ""
        )

        XCTAssertEqual(outcome, .output("Safari|Example|com.apple.Safari|/tmp/a.png"))
    }

    func testClassifyEmptyOutputIsAFailure() {
        let outcome = WindowCaptureProcessRunner.classify(terminationStatus: 0, standardOutput: "\n", standardError: "")

        XCTAssertEqual(outcome, .failed("AppleScript returned no output"))
    }

    func testClassifyAutomationDenialIsUnavailable() {
        let outcome = WindowCaptureProcessRunner.classify(
            terminationStatus: 1,
            standardOutput: "",
            standardError: "execution error: Not authorized to send Apple events to System Events. (-1743)\n"
        )

        guard case .unavailable(let reason) = outcome else {
            return XCTFail("Expected unavailable, got \(outcome)")
        }
        XCTAssertTrue(reason.contains("-1743"))
    }

    func testClassifyAssistiveAccessDenialIsUnavailable() {
        let outcome = WindowCaptureProcessRunner.classify(
            terminationStatus: 1,
            standardOutput: "",
            standardError: "osascript is not allowed assistive access. (-25211)\n"
        )

        guard case .unavailable = outcome else {
            return XCTFail("Expected unavailable, got \(outcome)")
        }
    }

    func testClassifyOtherFailureIsFailedNotUnavailable() {
        let outcome = WindowCaptureProcessRunner.classify(
            terminationStatus: 1,
            standardOutput: "",
            standardError: "syntax error: Expected end of line. (-2741)\n"
        )

        guard case .failed(let message) = outcome else {
            return XCTFail("Expected failed, got \(outcome)")
        }
        XCTAssertTrue(message.contains("-2741"))
    }

    func testClassifyFailureWithNoStderrReportsTheExitStatus() {
        let outcome = WindowCaptureProcessRunner.classify(terminationStatus: 7, standardOutput: "", standardError: "")

        XCTAssertEqual(outcome, .failed("AppleScript execution failed: exit status 7"))
    }

    func testRunReturnsTheScriptOutput() async {
        let outcome = await WindowCaptureProcessRunner.run(script: "return \"a|b|c|d\"")

        XCTAssertEqual(outcome, .output("a|b|c|d"))
    }

    func testRunTimesOutAHungScript() async {
        let outcome = await WindowCaptureProcessRunner.run(script: "delay 30", timeoutSeconds: 0.5)

        guard case .failed(let message) = outcome else {
            return XCTFail("Expected failed, got \(outcome)")
        }
        XCTAssertTrue(message.contains("timed out"))
    }
}
