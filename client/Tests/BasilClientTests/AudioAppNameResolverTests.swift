import XCTest
@testable import BasilClient

final class AudioAppNameResolverTests: XCTestCase {
    func testAVConferenceDaemonUsesAppleAudioLabel() {
        XCTAssertEqual(
            AudioAppNameResolver.displayName(forBundleID: "com.apple.avconferenced"),
            "Apple Audio"
        )
    }

    func testHelperBundleIDNormalizesToParent() {
        XCTAssertEqual(
            AudioAppNameResolver.parentBundleID(from: "com.google.Chrome.helper"),
            "com.google.Chrome"
        )
    }
}
