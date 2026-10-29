import Foundation
import XCTest
@testable import BasilClient

final class BridgeOpenPolicyTests: XCTestCase {
    private var temporaryDirectory: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
        temporaryDirectory = nil
        try super.tearDownWithError()
    }

    private func makeFile(_ name: String, permissions: Int = 0o644) throws -> URL {
        let url = temporaryDirectory.appendingPathComponent(name)
        try Data("content".utf8).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: permissions], ofItemAtPath: url.path)
        return url
    }

    func testDocumentsOpenNormally() throws {
        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: try makeFile("report.md")), .open)
        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: try makeFile("report.pdf")), .open)
        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: try makeFile("page.html")), .open)
    }

    func testScriptsAndLaunchersAreRevealedInsteadOfOpened() throws {
        for name in ["run.sh", "Run.COMMAND", "tool.py", "installer.pkg", "disk.dmg", "link.webloc", "automation.scpt"] {
            XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: try makeFile(name)), .revealInFinder, name)
        }
    }

    func testExecutableFilesWithoutAnExtensionAreRevealed() throws {
        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: try makeFile("binary", permissions: 0o755)), .revealInFinder)
    }

    func testPlainDirectoriesOpenButApplicationBundlesAreRevealed() throws {
        let folder = temporaryDirectory.appendingPathComponent("Folder", isDirectory: true)
        let bundle = temporaryDirectory.appendingPathComponent("Fake.app", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: bundle, withIntermediateDirectories: true)

        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: folder), .open)
        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: bundle), .revealInFinder)
    }

    func testMissingFilesAreReportedAndNotOpened() {
        let missing = temporaryDirectory.appendingPathComponent("missing.txt")

        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: missing), .missing)
        XCTAssertFalse(BridgeOpenPolicy.openLocalFile(missing))
    }

    func testPathTraversalIsStandardizedBeforeClassification() throws {
        _ = try makeFile("run.sh")
        let traversal = temporaryDirectory
            .appendingPathComponent("Folder", isDirectory: true)
            .appendingPathComponent("../run.sh")
        try FileManager.default.createDirectory(
            at: temporaryDirectory.appendingPathComponent("Folder", isDirectory: true),
            withIntermediateDirectories: true
        )

        XCTAssertEqual(BridgeOpenPolicy.localFileAction(for: traversal), .revealInFinder)
    }

    func testExternalURLSchemesAreAllowListed() {
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "https://example.com")!), .open)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "http://127.0.0.1:5173")!), .open)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "mailto:someone@example.com")!), .open)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "file:///tmp/run.sh")!), .localFile)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "javascript:alert(1)")!), .refuse)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "x-apple.systempreferences:com.apple.preference.security")!), .refuse)
        XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: URL(string: "vscode://file/tmp/run.sh")!), .refuse)
        XCTAssertFalse(BridgeOpenPolicy.openExternalURL(URL(string: "javascript:alert(1)")!))
    }
}
