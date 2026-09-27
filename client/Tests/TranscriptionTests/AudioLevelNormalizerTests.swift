import XCTest
@testable import BasilClient

final class AudioLevelNormalizerTests: XCTestCase {
    func testZeroAndInvalidSamplesNormalizeToSilence() {
        XCTAssertEqual(
            AudioLevelNormalizer.normalizedLevel(sumOfSquares: 0, sampleCount: 1),
            0
        )
        XCTAssertEqual(
            AudioLevelNormalizer.normalizedLevel(sumOfSquares: 1, sampleCount: 0),
            0
        )
    }

    func testSilenceFloorNormalizesToZero() {
        let rmsAtMinusFiftyDecibels: Float = 0.0031622776

        XCTAssertEqual(
            AudioLevelNormalizer.normalizedLevel(
                sumOfSquares: rmsAtMinusFiftyDecibels * rmsAtMinusFiftyDecibels,
                sampleCount: 1
            ),
            0,
            accuracy: 0.0001
        )
    }

    func testIntermediateLevelNormalizesLinearly() {
        let rmsAtMinusTwentyFiveDecibels: Float = 0.0562341325

        XCTAssertEqual(
            AudioLevelNormalizer.normalizedLevel(
                sumOfSquares: rmsAtMinusTwentyFiveDecibels * rmsAtMinusTwentyFiveDecibels,
                sampleCount: 1
            ),
            0.5,
            accuracy: 0.0001
        )
    }

    func testFullScaleNormalizesToOne() {
        XCTAssertEqual(
            AudioLevelNormalizer.normalizedLevel(sumOfSquares: 1, sampleCount: 1),
            1
        )
    }

    func testInt16SamplesUseSameNormalizationContract() {
        let samples: [Int16] = [0, Int16.max]

        XCTAssertGreaterThan(
            samples.withUnsafeBufferPointer {
                AudioLevelNormalizer.normalizedLevel(from: $0)
            },
            0.8
        )
    }
}
