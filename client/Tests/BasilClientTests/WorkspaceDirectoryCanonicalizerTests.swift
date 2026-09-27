import XCTest
@testable import BasilClient

final class WorkspaceDirectoryCanonicalizerTests: XCTestCase {
    private var tempRoot: URL!

    override func setUpWithError() throws {
        tempRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("WorkspaceDirectoryCanonicalizerTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempRoot)
    }

    func testCanonicalizeAcceptsAnExistingDirectory() throws {
        let result = WorkspaceDirectoryCanonicalizer.canonicalize(tempRoot)
        switch result {
        case .success(let path):
            XCTAssertEqual(path, tempRoot.resolvingSymlinksInPath().path)
        case .failure(let failure):
            XCTFail("Expected success, got \(failure)")
        }
    }

    func testCanonicalizeResolvesASymlinkToItsRealPath() throws {
        let realDir = tempRoot.appendingPathComponent("real", isDirectory: true)
        try FileManager.default.createDirectory(at: realDir, withIntermediateDirectories: true)
        let linkPath = tempRoot.appendingPathComponent("link", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: linkPath, withDestinationURL: realDir)

        let result = WorkspaceDirectoryCanonicalizer.canonicalize(linkPath)
        switch result {
        case .success(let path):
            XCTAssertEqual(path, realDir.resolvingSymlinksInPath().path)
        case .failure(let failure):
            XCTFail("Expected success, got \(failure)")
        }
    }

    func testCanonicalizeRejectsANonexistentDirectory() {
        let missing = tempRoot.appendingPathComponent("does-not-exist", isDirectory: true)
        guard case .failure(let failure) = WorkspaceDirectoryCanonicalizer.canonicalize(missing) else {
            return XCTFail("Expected failure")
        }
        XCTAssertEqual(failure, .doesNotExist)
    }

    func testCanonicalizeRejectsAFile() throws {
        let filePath = tempRoot.appendingPathComponent("file.txt")
        try "content".write(to: filePath, atomically: true, encoding: .utf8)
        guard case .failure(let failure) = WorkspaceDirectoryCanonicalizer.canonicalize(filePath) else {
            return XCTFail("Expected failure")
        }
        XCTAssertEqual(failure, .notADirectory)
    }

    func testCanonicalizeRejectsARelativeURL() {
        let relative = URL(string: "relative/workspace")!
        guard case .failure(let failure) = WorkspaceDirectoryCanonicalizer.canonicalize(relative) else {
            return XCTFail("Expected failure")
        }
        XCTAssertEqual(failure, .notAbsolute)
    }

    func testCanonicalizeRejectsAnUnreadableDirectory() throws {
        let restricted = tempRoot.appendingPathComponent("restricted", isDirectory: true)
        try FileManager.default.createDirectory(at: restricted, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: restricted.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: restricted.path) }

        guard NSUserName() != "root" else {
            throw XCTSkip("Root bypasses POSIX permission checks")
        }
        guard case .failure(let failure) = WorkspaceDirectoryCanonicalizer.canonicalize(restricted) else {
            return XCTFail("Expected failure")
        }
        XCTAssertEqual(failure, .notAccessible)
    }

    func testCanonicalizeRejectsAReadableButUnsearchableDirectory() throws {
        let restricted = tempRoot.appendingPathComponent("readable-but-unsearchable", isDirectory: true)
        try FileManager.default.createDirectory(at: restricted, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o400], ofItemAtPath: restricted.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: restricted.path) }

        guard NSUserName() != "root" else {
            throw XCTSkip("Root bypasses POSIX permission checks")
        }
        guard case .failure(let failure) = WorkspaceDirectoryCanonicalizer.canonicalize(restricted) else {
            return XCTFail("Expected failure")
        }
        XCTAssertEqual(failure, .notAccessible)
    }

    func testFailureUserMessagesAreNonblank() {
        let failures: [WorkspaceDirectoryCanonicalizer.Failure] = [.notAbsolute, .doesNotExist, .notADirectory, .notAccessible]
        for failure in failures {
            XCTAssertFalse(failure.userMessage.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }
}
