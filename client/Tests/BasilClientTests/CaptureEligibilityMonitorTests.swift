import XCTest
@testable import BasilClient

@MainActor
final class CaptureEligibilityMonitorTests: XCTestCase {
    func testReturnsNilWhenTheSystemIsEligible() {
        let monitor = CaptureEligibilityMonitor(
            observeSystemNotifications: false,
            idleSecondsProvider: { 10 }
        )

        XCTAssertNil(monitor.currentIneligibilityReason())
    }

    func testLockedSessionHasPriorityOverIdle() {
        let monitor = CaptureEligibilityMonitor(
            idleThresholdSeconds: 20,
            observeSystemNotifications: false,
            idleSecondsProvider: { 30 }
        )
        monitor.handleScreenLocked()

        XCTAssertEqual(monitor.currentIneligibilityReason(), "session_locked")
    }

    func testDisplaySleepAndPostWakeGraceAreIneligible() {
        let monitor = CaptureEligibilityMonitor(
            postWakeGraceSeconds: 30,
            observeSystemNotifications: false,
            idleSecondsProvider: { 0 }
        )
        monitor.handleDisplaySleep()
        XCTAssertEqual(monitor.currentIneligibilityReason(), "display_asleep")

        monitor.handleDisplayWake()
        XCTAssertEqual(monitor.currentIneligibilityReason(), "post_wake_grace")
    }

    func testIdleThresholdAndSettingsUpdatesAreApplied() {
        let monitor = CaptureEligibilityMonitor(
            idleThresholdSeconds: 30,
            observeSystemNotifications: false,
            idleSecondsProvider: { 45 }
        )
        XCTAssertEqual(monitor.currentIneligibilityReason(), "idle")

        monitor.applySettings(idleThresholdSeconds: 60, postWakeGraceSeconds: 0)
        XCTAssertNil(monitor.currentIneligibilityReason())

        monitor.applySettings(idleThresholdSeconds: 0, postWakeGraceSeconds: 0)
        XCTAssertNil(monitor.currentIneligibilityReason())
    }
}
