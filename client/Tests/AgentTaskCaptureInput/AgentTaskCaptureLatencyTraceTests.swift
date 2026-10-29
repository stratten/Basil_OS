import XCTest
@testable import BasilClient

final class AgentTaskCaptureLatencyTraceTests: XCTestCase {
    private final class FakeClock {
        var nanoseconds: UInt64 = 0
    }

    private final class LineRecorder {
        var lines: [String] = []
    }

    private func makeTrace(clock: FakeClock, recorder: LineRecorder) -> AgentTaskCaptureLatencyTrace {
        AgentTaskCaptureLatencyTrace(
            uptimeNanoseconds: { clock.nanoseconds },
            sink: { recorder.lines.append($0) }
        )
    }

    func testMarkBeforeBeginIsDroppedAndNotLogged() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        XCTAssertNil(trace.mark(.panelShown))
        XCTAssertTrue(recorder.lines.isEmpty)
    }

    func testMarkReportsMillisecondsSinceBegin() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        clock.nanoseconds = 10_000_000
        trace.begin()
        clock.nanoseconds = 10_000_000 + 42_900_000

        XCTAssertEqual(trace.mark(.panelShown), 42)
        XCTAssertEqual(recorder.lines.last, "[AgentTaskCaptureLatency] +42ms panelShown")
    }

    func testBeginResetsTheOrigin() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        clock.nanoseconds = 0
        trace.begin()
        clock.nanoseconds = 500_000_000
        XCTAssertEqual(trace.mark(.reactReady), 500)

        trace.begin()
        clock.nanoseconds = 520_000_000
        XCTAssertEqual(trace.mark(.reactReady), 20)
    }

    func testBeginLogsAZeroOffsetLine() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        trace.begin()

        XCTAssertEqual(recorder.lines, ["[AgentTaskCaptureLatency] +0ms begin"])
    }

    func testClockGoingBackwardsClampsToZero() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        clock.nanoseconds = 5_000_000
        trace.begin()
        clock.nanoseconds = 1_000_000

        XCTAssertEqual(trace.mark(.backendResponded), 0)
    }

    func testRepeatedMarksAreAllRecorded() {
        let clock = FakeClock()
        let recorder = LineRecorder()
        let trace = makeTrace(clock: clock, recorder: recorder)

        trace.begin()
        clock.nanoseconds = 1_000_000
        trace.mark(.windowCaptureStarted)
        clock.nanoseconds = 2_000_000
        trace.mark(.windowCaptureStarted)

        XCTAssertEqual(recorder.lines.count, 3)
    }
}
