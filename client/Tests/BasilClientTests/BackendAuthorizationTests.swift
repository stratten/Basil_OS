import Foundation
import XCTest
@testable import BasilClient

final class BackendAuthorizationTests: XCTestCase {
    private let backendPort = 8123
    private var temporaryDirectory: URL!
    private var store: BackendCredentialStore!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let fileURL = temporaryDirectory.appendingPathComponent("backend_credentials.json")
        try BackendCredentialTestFixtures.write(BackendCredentialTestFixtures.payload(), to: fileURL)
        store = BackendCredentialStore(fileURL: fileURL)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
        temporaryDirectory = nil
        store = nil
        try super.tearDownWithError()
    }

    private func url(_ string: String) -> URL {
        URL(string: string)!
    }

    func testBackendURLRecognitionRequiresLoopbackSchemeHostAndPort() {
        XCTAssertTrue(BackendAuthorization.isBackendURL(url("http://127.0.0.1:8123/health"), backendPort: backendPort))
        XCTAssertTrue(BackendAuthorization.isBackendURL(url("http://localhost:8123/api"), backendPort: backendPort))
        XCTAssertTrue(BackendAuthorization.isBackendURL(url("ws://localhost:8123/ws"), backendPort: backendPort))
        XCTAssertTrue(BackendAuthorization.isBackendURL(url("http://[::1]:8123/api"), backendPort: backendPort))

        XCTAssertFalse(BackendAuthorization.isBackendURL(url("https://localhost:8123/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("http://localhost:9000/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("http://localhost/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("http://attacker.example:8123/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("http://localhost.attacker.example:8123/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("http://user:pass@localhost:8123/api"), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorization.isBackendURL(url("file:///tmp/index.html"), backendPort: backendPort))
    }

    func testAuthorizedRequestAddsTheHostTokenOnlyForBackendURLs() throws {
        let hostToken = try XCTUnwrap(store.hostToken)

        let backend = BackendAuthorization.authorizedRequest(
            URLRequest(url: url("http://localhost:8123/api")),
            credentialStore: store,
            backendPort: backendPort
        )
        let foreign = BackendAuthorization.authorizedRequest(
            URLRequest(url: url("https://example.com/api")),
            credentialStore: store,
            backendPort: backendPort
        )

        XCTAssertEqual(backend.value(forHTTPHeaderField: BackendAuthorization.tokenHeader), hostToken)
        XCTAssertNil(foreign.value(forHTTPHeaderField: BackendAuthorization.tokenHeader))
    }

    func testRedirectStripsTheTokenForForeignTargetsAndKeepsItForTheBackend() throws {
        let hostToken = try XCTUnwrap(store.hostToken)
        var foreign = URLRequest(url: url("https://example.com/landing"))
        foreign.setValue(hostToken, forHTTPHeaderField: BackendAuthorization.tokenHeader)
        var backend = URLRequest(url: url("http://127.0.0.1:8123/api/"))
        backend.setValue(hostToken, forHTTPHeaderField: BackendAuthorization.tokenHeader)

        let redirectedForeign = BackendAuthorization.redirectRequest(foreign, credentialStore: store, backendPort: backendPort)
        let redirectedBackend = BackendAuthorization.redirectRequest(backend, credentialStore: store, backendPort: backendPort)

        XCTAssertNil(redirectedForeign.value(forHTTPHeaderField: BackendAuthorization.tokenHeader))
        XCTAssertEqual(redirectedBackend.value(forHTTPHeaderField: BackendAuthorization.tokenHeader), hostToken)
    }

    func testURLProtocolHandlesOnlyUnauthorizedBackendHTTPRequests() {
        var alreadyAuthorized = URLRequest(url: url("http://localhost:8123/api"))
        alreadyAuthorized.setValue("token", forHTTPHeaderField: BackendAuthorization.tokenHeader)

        XCTAssertTrue(BackendAuthorizationURLProtocol.canHandle(URLRequest(url: url("http://localhost:8123/api")), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorizationURLProtocol.canHandle(alreadyAuthorized, backendPort: backendPort))
        XCTAssertFalse(BackendAuthorizationURLProtocol.canHandle(URLRequest(url: url("ws://localhost:8123/ws")), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorizationURLProtocol.canHandle(URLRequest(url: url("https://example.com/api")), backendPort: backendPort))
        XCTAssertFalse(BackendAuthorizationURLProtocol.canHandle(URLRequest(url: url("http://localhost:9000/api")), backendPort: backendPort))
    }

    func testForwardedRequestIsMarkedHandledAndMaterializesStreamedBodies() {
        let body = Data("streamed body".utf8)
        var original = URLRequest(url: url("http://example.invalid/upload"))
        original.httpMethod = "POST"
        original.httpBodyStream = InputStream(data: body)

        let forwarded = BackendAuthorizationURLProtocol.forwardedRequest(from: original)

        XCTAssertEqual(forwarded.httpBody, body)
        XCTAssertNil(forwarded.httpBodyStream)
        XCTAssertEqual(forwarded.httpMethod, "POST")
        XCTAssertEqual(
            URLProtocol.property(forKey: BackendAuthorizationURLProtocol.handledPropertyKey, in: forwarded) as? Bool,
            true
        )
        var markedBackendRequest = URLRequest(url: url("http://localhost:8123/api"))
        let mutableBackendRequest = (markedBackendRequest as NSURLRequest).mutableCopy() as! NSMutableURLRequest
        URLProtocol.setProperty(true, forKey: BackendAuthorizationURLProtocol.handledPropertyKey, in: mutableBackendRequest)
        markedBackendRequest = mutableBackendRequest as URLRequest
        XCTAssertFalse(BackendAuthorizationURLProtocol.canHandle(markedBackendRequest, backendPort: backendPort))
    }
}
