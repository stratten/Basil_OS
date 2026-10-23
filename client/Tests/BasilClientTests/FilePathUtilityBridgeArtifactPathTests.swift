import XCTest
@testable import BasilClient

final class FilePathUtilityBridgeArtifactPathTests: XCTestCase {
    func testResolveBridgeArtifactPathAcceptsAbsolutePosixPath() {
        XCTAssertEqual(
            FilePathUtility.resolveBridgeArtifactPath("/Users/test/Documents/artifact.txt"),
            "/Users/test/Documents/artifact.txt"
        )
    }

    func testResolveBridgeArtifactPathAcceptsFileURL() {
        XCTAssertEqual(
            FilePathUtility.resolveBridgeArtifactPath("file:///Users/test/Documents/Artifact%20One.txt"),
            "/Users/test/Documents/Artifact One.txt"
        )
    }

    func testResolveBridgeArtifactPathAcceptsHFSPath() {
        XCTAssertEqual(
            FilePathUtility.resolveBridgeArtifactPath("Macintosh HD:Users:bridge-test:artifact.txt"),
            "/Users/bridge-test/artifact.txt"
        )
    }

    func testResolveBridgeArtifactPathRejectsBlankRelativeAndBareNames() {
        XCTAssertNil(FilePathUtility.resolveBridgeArtifactPath(""))
        XCTAssertNil(FilePathUtility.resolveBridgeArtifactPath("   "))
        XCTAssertNil(FilePathUtility.resolveBridgeArtifactPath("artifact.txt"))
        XCTAssertNil(FilePathUtility.resolveBridgeArtifactPath("Documents/artifact.txt"))
        XCTAssertNil(FilePathUtility.resolveBridgeArtifactPath(":Users:bridge-test:artifact.txt"))
    }
}
