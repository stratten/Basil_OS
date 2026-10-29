import Foundation
import XCTest
@testable import BasilClient

final class BackendCredentialStoreTests: XCTestCase {
    private var temporaryDirectory: URL!
    private var fileURL: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        fileURL = temporaryDirectory.appendingPathComponent("runtime/backend_credentials.json")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
        temporaryDirectory = nil
        fileURL = nil
        try super.tearDownWithError()
    }

    private func validPayload(host: String = String(repeating: "a", count: 64), webview: String = String(repeating: "b", count: 64)) -> [String: Any] {
        BackendCredentialTestFixtures.payload(host: host, webview: webview)
    }

    func testMissingFileYieldsNoCredentialsAndCreatesNothing() {
        let store = BackendCredentialStore(fileURL: fileURL)

        XCTAssertNil(store.current())
        XCTAssertNil(store.hostToken)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fileURL.path))
    }

    func testValidBackendFileIsRead() throws {
        try BackendCredentialTestFixtures.write(validPayload(), to: fileURL)
        let store = BackendCredentialStore(fileURL: fileURL)

        XCTAssertEqual(store.hostToken, String(repeating: "a", count: 64))
        XCTAssertEqual(store.webviewToken, String(repeating: "b", count: 64))
    }

    func testCurrentRereadsAfterTheBackendRotatesTheFile() throws {
        try BackendCredentialTestFixtures.write(validPayload(), to: fileURL)
        let store = BackendCredentialStore(fileURL: fileURL)
        XCTAssertEqual(store.hostToken, String(repeating: "a", count: 64))

        try BackendCredentialTestFixtures.atomicallyReplace(
            fileURL,
            with: validPayload(host: String(repeating: "c", count: 64), webview: String(repeating: "d", count: 64))
        )

        XCTAssertEqual(
            store.current(),
            BackendCredentials(hostToken: String(repeating: "c", count: 64), webviewToken: String(repeating: "d", count: 64))
        )
    }

    func testInvalidFileIsIgnoredAndNeverRewritten() throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: fileURL)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
        let store = BackendCredentialStore(fileURL: fileURL)

        XCTAssertNil(store.current())
        XCTAssertEqual(try Data(contentsOf: fileURL), Data("not json".utf8))
    }

    func testGroupReadableFileIsTreatedAsInvalid() throws {
        try BackendCredentialTestFixtures.write(validPayload(), to: fileURL, permissions: 0o644)
        let store = BackendCredentialStore(fileURL: fileURL)

        XCTAssertNil(store.current())

        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
        XCTAssertEqual(store.hostToken, String(repeating: "a", count: 64))
    }

    func testParseRejectsMalformedPayloads() throws {
        let malformed: [[String: Any]] = [
            ["version": true, "host_token": String(repeating: "a", count: 64), "webview_token": String(repeating: "b", count: 64)],
            ["version": 2, "host_token": String(repeating: "a", count: 64), "webview_token": String(repeating: "b", count: 64)],
            validPayload(host: String(repeating: "A", count: 64)),
            validPayload(host: String(repeating: "a", count: 63)),
            validPayload(host: String(repeating: "a", count: 64), webview: String(repeating: "a", count: 64)),
            ["version": 1, "host_token": String(repeating: "a", count: 64)],
        ]

        for payload in malformed {
            let data = try JSONSerialization.data(withJSONObject: payload)
            XCTAssertNil(BackendCredentials.parse(data), "\(payload)")
        }
        XCTAssertNil(BackendCredentials.parse(Data("[]".utf8)))
    }

    func testParseAcceptsTheBackendSerializationFormat() throws {
        let backendFormat = Data(
            #"{"created_at": "2026-01-01T00:00:00+00:00", "host_token": "\#(String(repeating: "c", count: 64))", "version": 1, "webview_token": "\#(String(repeating: "d", count: 64))"}"#.utf8
        )

        XCTAssertEqual(
            BackendCredentials.parse(backendFormat),
            BackendCredentials(hostToken: String(repeating: "c", count: 64), webviewToken: String(repeating: "d", count: 64))
        )
    }
}
