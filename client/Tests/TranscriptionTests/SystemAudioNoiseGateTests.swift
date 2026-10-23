import XCTest
@testable import BasilClient

final class SystemAudioNoiseGateTests: XCTestCase {
    func testCalibrationCompletesAtExactlyThirtyObservations() {
        var gate = SystemAudioNoiseGate()

        for _ in 0..<(SystemAudioNoiseGate.calibrationObservationCount - 1) {
            XCTAssertEqual(gate.filteredLevel(for: 0.1), 0)
            XCTAssertFalse(gate.isCalibrated)
        }

        XCTAssertEqual(gate.filteredLevel(for: 0.1), 0)
        XCTAssertTrue(gate.isCalibrated)
        XCTAssertEqual(gate.baseline, 0.1)
    }

    func testCalibratedBaselineIsGatedToZero() {
        var gate = calibratedGate(baseline: 0.1)

        XCTAssertEqual(gate.filteredLevel(for: 0.1), 0)
        XCTAssertEqual(gate.filteredLevel(for: 0.13), 0)
    }

    func testLevelAboveThresholdIsRebased() {
        var gate = calibratedGate(baseline: 0.1)

        XCTAssertEqual(
            gate.filteredLevel(for: 0.565),
            0.5,
            accuracy: 0.0001
        )
    }

    func testResetRemovesCalibration() {
        var gate = calibratedGate(baseline: 0.1)

        gate.reset()

        XCTAssertFalse(gate.isCalibrated)
        XCTAssertEqual(gate.filteredLevel(for: 1), 0)
    }

    func testHighBaselineCapsThresholdAtOne() {
        var gate = calibratedGate(baseline: 1)

        XCTAssertEqual(gate.filteredLevel(for: 1), 0)
    }

    private func calibratedGate(baseline: Float) -> SystemAudioNoiseGate {
        var gate = SystemAudioNoiseGate()
        for _ in 0..<SystemAudioNoiseGate.calibrationObservationCount {
            _ = gate.filteredLevel(for: baseline)
        }
        return gate
    }
}
