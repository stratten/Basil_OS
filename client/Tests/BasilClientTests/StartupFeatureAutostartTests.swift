import XCTest
@testable import BasilClient

final class StartupFeatureAutostartTests: XCTestCase {
    private struct Failure: Error {}

    /// A feature whose behavior each test scripts.
    private final class FakeFeature {
        var wanted = true
        var running = false
        var settingsReadFailures = 0
        var startFailures = 0
        var startsButDoesNotRun = 0
        private(set) var startCalls = 0
        private(set) var pauses: [TimeInterval] = []

        func run(retryDelays: [TimeInterval] = [1, 2, 3], shouldStop: @escaping () -> Bool = { false }) async -> StartupFeatureAutostart.Outcome {
            await StartupFeatureAutostart.ensureRunning(
                name: "Fake",
                shouldRun: {
                    if self.settingsReadFailures > 0 { self.settingsReadFailures -= 1; throw Failure() }
                    return self.wanted
                },
                isRunning: { self.running },
                start: {
                    self.startCalls += 1
                    if self.startFailures > 0 { self.startFailures -= 1; throw Failure() }
                    if self.startsButDoesNotRun > 0 { self.startsButDoesNotRun -= 1; return }
                    self.running = true
                },
                retryDelays: retryDelays,
                shouldStop: shouldStop,
                pause: { self.pauses.append($0) }
            )
        }
    }

    func testStartsAFeatureThatIsWantedAndNotRunning() async {
        let feature = FakeFeature()

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .running)
        XCTAssertEqual(feature.startCalls, 1)
        XCTAssertTrue(feature.pauses.isEmpty)
    }

    func testDoesNotStartAFeatureThatIsAlreadyRunning() async {
        let feature = FakeFeature()
        feature.running = true

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .running)
        XCTAssertEqual(feature.startCalls, 0)
    }

    func testDoesNothingWhenTheSettingsSayNotToStartAtLaunch() async {
        let feature = FakeFeature()
        feature.wanted = false

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .notWanted)
        XCTAssertEqual(feature.startCalls, 0)
    }

    func testTriesAgainAfterAStartRequestIsRefused() async {
        let feature = FakeFeature()
        feature.startFailures = 2

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .running)
        XCTAssertEqual(feature.startCalls, 3)
        XCTAssertEqual(feature.pauses, [1, 2])
    }

    func testTriesAgainWhenAStartIsAcceptedButTheFeatureNeverReportsRunning() async {
        let feature = FakeFeature()
        feature.startsButDoesNotRun = 1

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .running)
        XCTAssertEqual(feature.startCalls, 2)
    }

    func testTriesAgainAfterTheSettingsCouldNotBeRead() async {
        let feature = FakeFeature()
        feature.settingsReadFailures = 2

        let outcome = await feature.run()

        XCTAssertEqual(outcome, .running)
        XCTAssertEqual(feature.pauses, [1, 2])
    }

    func testGivesUpAfterTheLastDelayAndSaysSo() async {
        let feature = FakeFeature()
        feature.startFailures = 100

        let outcome = await feature.run(retryDelays: [1, 2])

        XCTAssertEqual(outcome, .gaveUp)
        XCTAssertEqual(feature.startCalls, 3, "One attempt, then one after each delay")
        XCTAssertEqual(feature.pauses, [1, 2])
    }

    func testStopsWithoutStartingAnythingWhenTheAppIsQuitting() async {
        let feature = FakeFeature()

        let outcome = await feature.run(shouldStop: { true })

        XCTAssertEqual(outcome, .stopped)
        XCTAssertEqual(feature.startCalls, 0)
    }

    func testStopsBetweenAttemptsWhenTheAppStartsQuitting() async {
        let feature = FakeFeature()
        feature.startFailures = 100
        var checks = 0

        let outcome = await feature.run(shouldStop: { checks += 1; return checks > 2 })

        XCTAssertEqual(outcome, .stopped)
        XCTAssertEqual(feature.startCalls, 2)
    }

    func testTheDefaultScheduleRunsForRoughlyFiveMinutes() {
        let total = StartupFeatureAutostart.defaultRetryDelays.reduce(0, +)

        XCTAssertGreaterThanOrEqual(total, 240)
        XCTAssertLessThanOrEqual(total, 420)
    }
}
