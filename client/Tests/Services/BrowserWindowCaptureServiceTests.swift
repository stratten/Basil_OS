import XCTest
import CoreGraphics
@testable import BasilClient

final class BrowserWindowCaptureServiceTests: XCTestCase {
    private func candidate(
        id: CGWindowID,
        owner: String = "Google Chrome",
        title: String = "",
        bounds: CGRect = CGRect(x: 100, y: 80, width: 1200, height: 800),
        layer: Int = 0
    ) -> BrowserWindowCandidate {
        BrowserWindowCandidate(windowID: id, ownerName: owner, ownerPID: 1, title: title, bounds: bounds, layer: layer)
    }

    private let target = BrowserWindowCaptureTarget(
        ownerName: "Google Chrome",
        bounds: CGRect(x: 100, y: 80, width: 1200, height: 800),
        title: "Annual Report"
    )

    func testMatchesTheOnlyWindowWithTheSameFrame() {
        let outcome = BrowserWindowCaptureService.match(
            target: target,
            candidates: [candidate(id: 7), candidate(id: 9, owner: "Cursor")]
        )

        XCTAssertEqual(outcome, .matched(candidate(id: 7)))
    }

    func testIgnoresAnotherAppEvenWhenItIsInTheSameFrame() {
        let outcome = BrowserWindowCaptureService.match(target: target, candidates: [candidate(id: 9, owner: "Cursor")])

        XCTAssertEqual(outcome, .noWindow)
    }

    func testToleratesSmallFrameDifferences() {
        let nearby = candidate(id: 7, bounds: CGRect(x: 103, y: 82, width: 1197, height: 804))

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [nearby]), .matched(nearby))
    }

    func testRejectsAFrameOutsideTheTolerance() {
        let far = candidate(id: 7, bounds: CGRect(x: 140, y: 80, width: 1200, height: 800))

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [far]), .noWindow)
    }

    func testIgnoresNonStandardLayers() {
        let overlay = candidate(id: 7, layer: 25)

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [overlay]), .noWindow)
    }

    func testTitleBreaksATieBetweenWindowsWithTheSameFrame() {
        let other = candidate(id: 7, title: "Inbox - Google Chrome")
        let wanted = candidate(id: 8, title: "Annual Report - Google Chrome - Work")

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [other, wanted]), .matched(wanted))
    }

    func testTieWithoutATitleMatchIsAmbiguousRatherThanGuessed() {
        let first = candidate(id: 7, title: "Inbox")
        let second = candidate(id: 8, title: "Calendar")

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [first, second]), .ambiguous(count: 2))
    }

    func testOwnerNameComparisonIgnoresCase() {
        let lowercase = candidate(id: 7, owner: "google chrome")

        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: [lowercase]), .matched(lowercase))
    }

    func testPayloadParsesIntoATarget() {
        let payload: [String: Any] = [
            "owner_name": "Google Chrome",
            "bounds": ["x": 100, "y": 80.5, "width": 1200, "height": 800],
            "title": "Annual Report",
        ]

        XCTAssertEqual(
            BrowserWindowCaptureTarget(payload: payload),
            BrowserWindowCaptureTarget(ownerName: "Google Chrome", bounds: CGRect(x: 100, y: 80.5, width: 1200, height: 800), title: "Annual Report")
        )
    }

    func testPayloadWithoutATitleStillParses() {
        let payload: [String: Any] = ["owner_name": "Safari", "bounds": ["x": 0, "y": 0, "width": 900, "height": 700]]

        XCTAssertEqual(BrowserWindowCaptureTarget(payload: payload)?.title, nil)
        XCTAssertNotNil(BrowserWindowCaptureTarget(payload: payload))
    }

    func testMalformedPayloadsAreRejected() {
        XCTAssertNil(BrowserWindowCaptureTarget(payload: nil))
        XCTAssertNil(BrowserWindowCaptureTarget(payload: "chrome"))
        XCTAssertNil(BrowserWindowCaptureTarget(payload: ["owner_name": "", "bounds": ["x": 0, "y": 0, "width": 10, "height": 10]]))
        XCTAssertNil(BrowserWindowCaptureTarget(payload: ["owner_name": "Google Chrome"]))
        XCTAssertNil(BrowserWindowCaptureTarget(payload: ["owner_name": "Google Chrome", "bounds": ["x": 0, "y": 0, "width": 0, "height": 10]]))
        XCTAssertNil(BrowserWindowCaptureTarget(payload: ["owner_name": "Google Chrome", "bounds": ["x": 0, "y": 0]]))
    }

    func testNoCandidatesIsNoWindow() {
        XCTAssertEqual(BrowserWindowCaptureService.match(target: target, candidates: []), .noWindow)
    }
}
