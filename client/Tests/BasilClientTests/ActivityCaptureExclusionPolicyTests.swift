import XCTest
import AppKit
@testable import BasilClient

@MainActor
final class ActivityCaptureExclusionPolicyTests: XCTestCase {
    private var tempCapturePath: String = ""

    override func setUp() {
        super.setUp()
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("basil-capture-test-\(UUID().uuidString).png")
        let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: 9,
            pixelsHigh: 8,
            bitsPerSample: 8,
            samplesPerPixel: 1,
            hasAlpha: false,
            isPlanar: false,
            colorSpaceName: .deviceWhite,
            bitmapFormat: [],
            bytesPerRow: 0,
            bitsPerPixel: 0
        )!
        for row in 0..<8 {
            for column in 0..<9 {
                bitmap.setColor(
                    column.isMultiple(of: 2) ? .white : .black,
                    atX: column,
                    y: row
                )
            }
        }
        try! bitmap.representation(using: .png, properties: [:])!.write(to: tempURL)
        tempCapturePath = tempURL.path
    }

    override func tearDown() {
        try? FileManager.default.removeItem(atPath: tempCapturePath)
        super.tearDown()
    }

    func testParseSuccessOutputIncludesBundleIdentifier() {
        let result = WindowCaptureService.shared.parseAppleScriptOutput(
            "Safari|Example|com.apple.Safari|\(tempCapturePath)"
        )
        XCTAssertTrue(result.success)
        XCTAssertEqual(result.bundleIdentifier, "com.apple.Safari")
        XCTAssertFalse(result.policySkipped)
        XCTAssertEqual(result.imagePath, tempCapturePath)
        XCTAssertNotNil(result.perceptualHash)
    }

    func testParsePolicySkipOutput() {
        let result = WindowCaptureService.shared.parseAppleScriptOutput(
            "TextEdit||com.apple.TextEdit|policy_skip:excluded_app"
        )
        XCTAssertFalse(result.success)
        XCTAssertTrue(result.policySkipped)
        XCTAssertEqual(result.bundleIdentifier, "com.apple.TextEdit")
        XCTAssertEqual(result.error, "excluded_app")
        XCTAssertNil(result.imagePath)
    }

    func testParseErrorOutputPreservesBundleIdentifier() {
        let result = WindowCaptureService.shared.parseAppleScriptOutput(
            "Safari|Example|com.apple.Safari|error:window bounds unavailable"
        )
        XCTAssertFalse(result.success)
        XCTAssertEqual(result.bundleIdentifier, "com.apple.Safari")
        XCTAssertEqual(result.error, "window bounds unavailable")
    }

    func testMakeAppleScriptEscapesBundleIdentifiersDeterministically() {
        let script = WindowCaptureService.shared.makeAppleScript(
            excludedBundleIDs: ["com.z.test", "com.a.app"]
        )
        XCTAssertTrue(script.contains("{\"com.a.app\", \"com.z.test\"}"))
    }

    func testEmptyExclusionListRendersEmptyAppleScriptSet() {
        let script = WindowCaptureService.shared.makeAppleScript(excludedBundleIDs: [])
        XCTAssertTrue(script.contains("set excludedBundleIDs to {}"))
    }

    func testSkippedFactoryShape() {
        let result = WindowCaptureService.CaptureResult.skipped(
            appName: "Basil",
            bundleIdentifier: "com.stratten.basil",
            reason: "excluded_app"
        )
        XCTAssertTrue(result.policySkipped)
        XCTAssertEqual(result.windowTitle, "")
        XCTAssertNil(result.imagePath)
    }

    func testAutomaticPolicyPreservesExactBundleIdentifier() {
        let exclusions = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: "automatic activity capture",
            rawBundleIDs: ["com.apple.TextEdit"]
        )
        XCTAssertTrue(exclusions.contains("com.apple.TextEdit"))
    }

    func testAutomaticPolicyNormalizesHelperToParentBundleIdentifier() {
        let exclusions = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: "automatic activity capture",
            rawBundleIDs: ["com.google.Chrome.helper"]
        )
        XCTAssertTrue(exclusions.contains("com.google.Chrome"))
        XCTAssertFalse(exclusions.contains("com.google.Chrome.helper"))
    }

    func testAutomaticPolicyDeduplicatesCaseInsensitively() {
        let exclusions = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: "automatic activity capture",
            rawBundleIDs: ["com.apple.TextEdit", "COM.APPLE.TEXTEDIT"]
        )
        XCTAssertEqual(
            exclusions.filter { $0.caseInsensitiveCompare("com.apple.TextEdit") == .orderedSame }.count,
            1
        )
    }

    func testAutomaticPolicyAllowsBasilCaptureWhenNoAppsAreExcluded() {
        let exclusions = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: "automatic activity capture",
            rawBundleIDs: []
        )
        XCTAssertTrue(exclusions.isEmpty)
    }

    func testNonAutomaticRequestsBypassPolicy() {
        let exclusions = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: "agent_task",
            rawBundleIDs: ["com.stratten.basil", "com.apple.TextEdit"]
        )
        XCTAssertTrue(exclusions.isEmpty)
    }
}
