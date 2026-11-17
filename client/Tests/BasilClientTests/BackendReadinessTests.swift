import XCTest
@testable import BasilClient

final class BackendReadinessTests: XCTestCase {
    private final class Counter: @unchecked Sendable {
        private let lock = NSLock()
        private var value = 0

        @discardableResult
        func increment() -> Int {
            lock.lock()
            defer { lock.unlock() }
            value += 1
            return value
        }

        var current: Int {
            lock.lock()
            defer { lock.unlock() }
            return value
        }
    }

    func testReturnsTrueAsSoonAsTheProbeSucceeds() async {
        let probes = Counter()

        let ready = await BackendReadiness.wait(
            pollInterval: 0.001,
            probe: { probes.increment() >= 3 },
            shouldStop: { false }
        )

        XCTAssertTrue(ready)
        XCTAssertEqual(probes.current, 3)
    }

    func testKeepsWaitingPastTheOldThirtySecondGiveUpPoint() async {
        // The old wait gave up after 60 probes (30 seconds at 0.5 second intervals). This one must still be waiting after that many.
        let probes = Counter()

        let ready = await BackendReadiness.wait(
            pollInterval: 0.0005,
            probe: { probes.increment() >= 200 },
            shouldStop: { false }
        )

        XCTAssertTrue(ready)
        XCTAssertEqual(probes.current, 200)
    }

    func testStopsWithoutProbingWhenAskedToStopBeforeStarting() async {
        let probes = Counter()

        let ready = await BackendReadiness.wait(
            pollInterval: 0.001,
            probe: { probes.increment(); return true },
            shouldStop: { true }
        )

        XCTAssertFalse(ready)
        XCTAssertEqual(probes.current, 0)
    }

    func testStopsWaitingWhenToldToStopPartWayThrough() async {
        let probes = Counter()

        let ready = await BackendReadiness.wait(
            pollInterval: 0.001,
            probe: { probes.increment(); return false },
            shouldStop: { probes.current >= 5 }
        )

        XCTAssertFalse(ready)
        XCTAssertEqual(probes.current, 5)
    }

    func testCancelingTheWaitingTaskEndsTheWait() async {
        let task = Task {
            await BackendReadiness.wait(
                pollInterval: 0.001,
                probe: { false },
                shouldStop: { Task.isCancelled }
            )
        }
        try? await Task.sleep(nanoseconds: 20_000_000)
        task.cancel()

        let ready = await task.value

        XCTAssertFalse(ready)
    }
}
