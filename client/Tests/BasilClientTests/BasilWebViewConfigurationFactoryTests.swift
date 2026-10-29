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

    func testBundledPageAccessAllowsFileModulesButNeverUniversalFileAccess() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8000 },
            trustedAssetRootPath: trustedRoot
        )

        XCTAssertEqual(configuration.preferences.value(forKey: "allowFileAccessFromFileURLs") as? Bool, true)
        XCTAssertNotEqual(configuration.value(forKey: "allowUniversalAccessFromFileURLs") as? Bool, true)
    }

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

        // The blueprint reveal flag script comes first, then the text size script, then the backend authorization script.
        let scripts = configuration.userContentController.userScripts
        XCTAssertEqual(scripts.count, 3)
        XCTAssertEqual(scripts.last?.injectionTime, .atDocumentStart)
        XCTAssertEqual(scripts.last?.isForMainFrameOnly, true)
        XCTAssertTrue(scripts.last?.source.contains(validToken) ?? false)
        XCTAssertFalse(scripts.last?.source.contains(hostToken) ?? true)
    }

    func testMakeConfigurationBeforeTheBackendWritesCredentialsStillInstallsTheRefreshingScript() throws {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: trustedRoot
        )

        let source = try XCTUnwrap(configuration.userContentController.userScripts.last?.source)
        XCTAssertEqual(configuration.userContentController.userScripts.count, 3)
        XCTAssertTrue(source.contains("let token = null;"))
    }

    func testMakeConfigurationWithoutATrustedRootInstallsOnlyTheBlueprintRevealFlagAndTheTextScale() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil,
            blueprintReveal: false
        )

        let scripts = configuration.userContentController.userScripts
        XCTAssertEqual(scripts.count, 2)
        XCTAssertEqual(scripts.first?.source, "window.basilBlueprintReveal = false;")
        XCTAssertEqual(scripts.last?.source, TextScaleStep.firstPaintScriptSource(scale: AestheticSystem.textScale))
    }

    func testMakeConfigurationInstallsTheTextScaleAtDocumentStartForTheMainFrame() throws {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil,
            textScale: 1.25
        )

        let script = try XCTUnwrap(configuration.userContentController.userScripts.last)
        XCTAssertTrue(script.source.contains("var v='1.25';"))
        XCTAssertTrue(script.source.contains("--text-scale"))
        XCTAssertEqual(script.injectionTime, .atDocumentStart)
        XCTAssertTrue(script.isForMainFrameOnly)
    }

    func testMakeConfigurationDefaultsTheTextScaleToTheUsersSetting() throws {
        AestheticSystem.loadFromSettings(AppearanceSettings(textScale: 1.4))
        defer { AestheticSystem.loadFromSettings(AppearanceSettings()) }

        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil
        )

        XCTAssertTrue(try XCTUnwrap(configuration.userContentController.userScripts.last).source.contains("var v='1.4';"))
    }

    func testMakeConfigurationInstallsTheBlueprintRevealFlagAtDocumentStartForTheMainFrame() {
        let enabled = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil,
            blueprintReveal: true
        ).userContentController.userScripts.first

        XCTAssertEqual(enabled?.source, "window.basilBlueprintReveal = true;")
        XCTAssertEqual(enabled?.injectionTime, .atDocumentStart)
        XCTAssertEqual(enabled?.isForMainFrameOnly, true)
    }

    func testMakeConfigurationDefaultsTheBlueprintRevealFlagToTheUsersSetting() {
        AestheticSystem.loadFromSettings(AppearanceSettings(blueprintReveal: true))
        defer { AestheticSystem.loadFromSettings(AppearanceSettings()) }

        let configuration = BasilWebViewConfigurationFactory.makeConfiguration(
            credentialStore: store,
            backendPortProvider: { 8123 },
            trustedAssetRootPath: nil
        )

        XCTAssertEqual(configuration.userContentController.userScripts.first?.source, "window.basilBlueprintReveal = true;")
    }
}
