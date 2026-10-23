import Foundation
import WebKit
import XCTest
@testable import BasilClient

@MainActor
final class BasilWebViewConfigurationFactoryTests: XCTestCase {
    private var temporaryDirectory: URL!
    private var store: BackendCredentialStore!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        store = BackendCredentialStore(fileURL: temporaryDirectory.appendingPathComponent("backend_credentials.json"))
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
        temporaryDirectory = nil
        store = nil
        try super.tearDownWithError()
    }

    private let trustedRoot = "/Applications/Basil.app/Contents/Resources"
    private let validToken = String(repeating: "e", count: 64)

    func testScriptSeedsTheInitialTokenPortTrustedRootAndHandlerName() throws {
        let source = try XCTUnwrap(
            BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(
                initialWebviewToken: validToken,
                initialBackendPort: 8123,
                trustedAssetRootPath: trustedRoot
            )
        )

        XCTAssertTrue(source.contains(#"let token = "\#(validToken)";"#))
        XCTAssertTrue(source.contains(#"let backendPort = "8123";"#))
        XCTAssertTrue(source.contains(#"const trustedRoot = "\/Applications\/Basil.app\/Contents\/Resources\/";"#))
        XCTAssertTrue(source.contains(#"const handlerName = "basilBackendCredentials";"#))
        XCTAssertTrue(source.contains(#"const tokenHeader = "X-Basil-Token";"#))
        XCTAssertTrue(source.contains(#"const acceptProtocol = "basil.v1";"#))
        XCTAssertTrue(source.contains(#"const tokenProtocolPrefix = "basil.token.";"#))
        XCTAssertTrue(source.contains("window.location.protocol !== 'file:'"))
        XCTAssertTrue(source.contains("socket.addEventListener('close', () => { refreshCredentials(); });"))
        XCTAssertTrue(source.contains("return refreshCredentials().then(() => {"))
    }

    func testScriptStartsWithANullTokenWhenNoValidTokenExistsYet() throws {
        for initialToken in [nil, "not-a-token"] as [String?] {
            let source = try XCTUnwrap(
                BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(
                    initialWebviewToken: initialToken,
                    initialBackendPort: 8123,
                    trustedAssetRootPath: trustedRoot
                )
            )

            XCTAssertTrue(source.contains("let token = null;"), String(describing: initialToken))
            XCTAssertFalse(source.contains("not-a-token"))
        }
    }

    func testScriptEscapesUnsafeCharactersInTheTrustedRoot() throws {
        let source = try XCTUnwrap(
            BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(
                initialWebviewToken: validToken,
                initialBackendPort: 8123,
                trustedAssetRootPath: #"/tmp/quote"; alert(1); ""#
            )
        )

        XCTAssertTrue(source.contains(#"const trustedRoot = "\/tmp\/quote\"; alert(1); \"\/";"#))
        XCTAssertFalse(source.contains(#"const trustedRoot = "/tmp/quote"; alert(1);"#))
    }

    func testScriptIsOmittedForAnInvalidPortOrRoot() {
        XCTAssertNil(BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(initialWebviewToken: validToken, initialBackendPort: 0, trustedAssetRootPath: "/r"))
        XCTAssertNil(BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(initialWebviewToken: validToken, initialBackendPort: 70_000, trustedAssetRootPath: "/r"))
        XCTAssertNil(BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(initialWebviewToken: validToken, initialBackendPort: 8123, trustedAssetRootPath: nil))
        XCTAssertNil(BasilWebViewConfigurationFactory.backendAuthorizationScriptSource(initialWebviewToken: validToken, initialBackendPort: 8123, trustedAssetRootPath: ""))
    }

    func testReplyReturnsCurrentCredentialsToTrustedMainFramePages() throws {
        let reply = BackendCredentialMessageHandler.reply(
            isMainFrame: true,
            frameURL: URL(fileURLWithPath: trustedRoot + "/frontend/chat/index.html"),
            trustedAssetRootPath: trustedRoot,
            webviewToken: validToken,
            backendPort: 8124
        )

        XCTAssertNil(reply.1)
        XCTAssertEqual(reply.0 as? [String: String], ["token": validToken, "port": "8124"])
    }

    func testReplyRefusesSubframesForeignFilesAndRemotePages() {
        let refusedFrames: [(Bool, URL?)] = [
            (false, URL(fileURLWithPath: trustedRoot + "/frontend/chat/index.html")),
            (true, URL(fileURLWithPath: "/Users/someone/Downloads/page.html")),
            (true, URL(fileURLWithPath: trustedRoot + "Evil/index.html")),
            (true, URL(fileURLWithPath: trustedRoot + "/../../../../tmp/page.html")),
            (true, URL(string: "https://example.com" + trustedRoot + "/index.html")),
            (true, nil),
        ]

        for (isMainFrame, frameURL) in refusedFrames {
            let reply = BackendCredentialMessageHandler.reply(
                isMainFrame: isMainFrame,
                frameURL: frameURL,
                trustedAssetRootPath: trustedRoot,
                webviewToken: validToken,
                backendPort: 8123
            )

            XCTAssertNil(reply.0, String(describing: frameURL))
            XCTAssertEqual(reply.1, "untrusted_frame", String(describing: frameURL))
        }
    }

    func testReplyReportsMissingCredentialsWithoutAToken() {
        for webviewToken in [nil, "not-a-token"] as [String?] {
            let reply = BackendCredentialMessageHandler.reply(
                isMainFrame: true,
                frameURL: URL(fileURLWithPath: trustedRoot + "/frontend/chat/index.html"),
                trustedAssetRootPath: trustedRoot,
                webviewToken: webviewToken,
                backendPort: 8123
            )

            XCTAssertNil(reply.0)
            XCTAssertEqual(reply.1, "credentials_unavailable")
        }
    }

    func testMakeConfigurationInstallsOneMainFrameDocumentStartScript() throws {
        let hostToken = String(repeating: "c", count: 64)
        try BackendCredentialTestFixtures.write(
            BackendCredentialTestFixtures.payload(host: hostToken, webview: validToken),
            to: store.fileURL
        )

        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: trustedRoot
        )

        let scripts = configuration.userContentController.userScripts
        XCTAssertEqual(scripts.count, 1)
        XCTAssertEqual(scripts.first?.injectionTime, .atDocumentStart)
        XCTAssertEqual(scripts.first?.isForMainFrameOnly, true)
        XCTAssertTrue(scripts.first?.source.contains(validToken) ?? false)
        XCTAssertFalse(scripts.first?.source.contains(hostToken) ?? true)
    }

    func testMakeConfigurationBeforeTheBackendWritesCredentialsStillInstallsTheRefreshingScript() throws {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: trustedRoot
        )

        let source = try XCTUnwrap(configuration.userContentController.userScripts.first?.source)
        XCTAssertEqual(configuration.userContentController.userScripts.count, 1)
        XCTAssertTrue(source.contains("let token = null;"))
    }

    func testMakeConfigurationWithoutATrustedRootInstallsNoScript() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil
        )

        XCTAssertTrue(configuration.userContentController.userScripts.isEmpty)
    }
}
