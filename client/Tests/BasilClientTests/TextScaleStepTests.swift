import XCTest
@testable import BasilClient

final class TextScaleStepTests: XCTestCase {
    func testTheOfferedStepsAreTheFiveBackendSteps() {
        XCTAssertEqual(TextScaleStep.steps, [0.9, 1.0, 1.1, 1.25, 1.4])
        XCTAssertEqual(TextScaleStep.defaultScale, 1.0)
    }

    func testEveryOfferedStepSnapsToItself() {
        for step in TextScaleStep.steps {
            XCTAssertEqual(TextScaleStep.snapped(step), step)
        }
    }

    func testValuesBetweenStepsSnapToTheNearest() {
        XCTAssertEqual(TextScaleStep.snapped(0.96), 1.0)
        XCTAssertEqual(TextScaleStep.snapped(1.04), 1.0)
        XCTAssertEqual(TextScaleStep.snapped(1.12), 1.1)
        XCTAssertEqual(TextScaleStep.snapped(1.2), 1.25)
        XCTAssertEqual(TextScaleStep.snapped(1.33), 1.4)
    }

    func testValuesOutsideTheRangeClampToTheEnds() {
        XCTAssertEqual(TextScaleStep.snapped(0.1), 0.9)
        XCTAssertEqual(TextScaleStep.snapped(-3), 0.9)
        XCTAssertEqual(TextScaleStep.snapped(9), 1.4)
    }

    func testNonFiniteValuesMeanOneHundredPercent() {
        XCTAssertEqual(TextScaleStep.snapped(.nan), 1.0)
        XCTAssertEqual(TextScaleStep.snapped(.infinity), 1.0)
        XCTAssertEqual(TextScaleStep.snapped(-.infinity), 1.0)
    }

    func testLargerWalksUpOneStepAndStopsAtTheLargest() {
        XCTAssertEqual(TextScaleStep.larger(than: 0.9), 1.0)
        XCTAssertEqual(TextScaleStep.larger(than: 1.0), 1.1)
        XCTAssertEqual(TextScaleStep.larger(than: 1.1), 1.25)
        XCTAssertEqual(TextScaleStep.larger(than: 1.25), 1.4)
        XCTAssertEqual(TextScaleStep.larger(than: 1.4), 1.4)
    }

    func testSmallerWalksDownOneStepAndStopsAtTheSmallest() {
        XCTAssertEqual(TextScaleStep.smaller(than: 1.4), 1.25)
        XCTAssertEqual(TextScaleStep.smaller(than: 1.25), 1.1)
        XCTAssertEqual(TextScaleStep.smaller(than: 1.1), 1.0)
        XCTAssertEqual(TextScaleStep.smaller(than: 1.0), 0.9)
        XCTAssertEqual(TextScaleStep.smaller(than: 0.9), 0.9)
    }

    func testLargerAndSmallerStartFromTheNearestStepWhenGivenAnOffStepValue() {
        XCTAssertEqual(TextScaleStep.larger(than: 1.2), 1.4)
        XCTAssertEqual(TextScaleStep.smaller(than: 1.2), 1.1)
        XCTAssertEqual(TextScaleStep.larger(than: .nan), 1.1)
        XCTAssertEqual(TextScaleStep.smaller(than: .nan), 0.9)
    }

    func testPercentLabelsAreWholeNumbers() {
        XCTAssertEqual(TextScaleStep.percentLabel(for: 0.9), "90%")
        XCTAssertEqual(TextScaleStep.percentLabel(for: 1.0), "100%")
        XCTAssertEqual(TextScaleStep.percentLabel(for: 1.25), "125%")
        XCTAssertEqual(TextScaleStep.percentLabel(for: 1.4), "140%")
    }

    func testFirstPaintScriptSetsTheScaleOnTheRootAndWaitsForItWhenMissing() {
        let script = TextScaleStep.firstPaintScriptSource(scale: 1.25)
        XCTAssertTrue(script.contains("var v='1.25';"))
        XCTAssertTrue(script.contains("r.style.setProperty('--text-scale',v)"))
        XCTAssertTrue(script.contains("new MutationObserver"))
    }

    func testFirstPaintScriptNeverEmbedsAnUnsnappedValue() {
        XCTAssertTrue(TextScaleStep.firstPaintScriptSource(scale: 3.7).contains("var v='1.4';"))
        XCTAssertTrue(TextScaleStep.firstPaintScriptSource(scale: .nan).contains("var v='1';"))
    }
}
