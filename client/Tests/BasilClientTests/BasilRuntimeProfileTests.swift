import Foundation
import XCTest
@testable import BasilClient

final class BasilRuntimeProfileTests: XCTestCase {
    private var temporaryDirectory: URL!
    private var sessionBaseURL: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        sessionBaseURL = temporaryDirectory.appendingPathComponent("Library/Application Support/BasilValidation/sessions")
        try FileManager.default.createDirectory(at: sessionBaseURL, withIntermediateDirectories: true)
        BasilRuntimeProfile.resetForTesting()
    }

    override func tearDownWithError() throws {
        BasilRuntimeProfile.resetForTesting()
        try? FileManager.default.removeItem(at: temporaryDirectory)
        temporaryDirectory = nil
        sessionBaseURL = nil
        try super.tearDownWithError()
    }

    func testNoValidationFlagReturnsNormalProfile() {
        XCTAssertEqual(
            BasilRuntimeProfile.bootstrap(arguments: ["BasilClient"], sessionBaseURL: sessionBaseURL),
            .success(.normal)
        )
    }

    func testValidManifestReturnsValidationProfile() throws {
        let manifestURL = try writeManifest()

        let result = BasilRuntimeProfile.bootstrap(
            arguments: ["BasilClient", "--validation-session", manifestURL.path],
            sessionBaseURL: sessionBaseURL
        )

        guard case .success(.validation(let manifest)) = result else {
            return XCTFail("Expected validated session manifest, got \(result)")
        }
        XCTAssertEqual(manifest.sessionID, "live-preview")
        XCTAssertEqual(manifest.backendURL.absoluteString, "http://127.0.0.1:8765")
    }

    func testDuplicateValidationFlagsAreRejected() throws {
        let manifestURL = try writeManifest()

        XCTAssertEqual(
            BasilRuntimeProfile.bootstrap(
                arguments: ["BasilClient", "--validation-session", manifestURL.path, "--validation-session", manifestURL.path],
                sessionBaseURL: sessionBaseURL
            ),
            .failure("Validation launch rejected: --validation-session may be supplied only once.")
        )
    }

    func testMissingValidationManifestValueIsRejected() {
        XCTAssertEqual(
            BasilRuntimeProfile.bootstrap(arguments: ["BasilClient", "--validation-session"], sessionBaseURL: sessionBaseURL),
            .failure("Validation launch rejected: missing --validation-session value.")
        )
    }

    func testRelativeManifestPathIsRejected() {
        XCTAssertEqual(
            BasilRuntimeProfile.bootstrap(arguments: ["BasilClient", "--validation-session", "manifest.json"], sessionBaseURL: sessionBaseURL),
            .failure("Validation launch rejected: manifest path must be absolute.")
        )
    }

    func testManifestRejectsNonLoopbackBackendURL() throws {
        let manifestURL = try writeManifest(backendURL: URL(string: "https://example.com:443")!)

        let result = BasilRuntimeProfile.bootstrap(
            arguments: ["BasilClient", "--validation-session", manifestURL.path],
            sessionBaseURL: sessionBaseURL
        )

        XCTAssertEqual(result, .failure("Validation launch rejected: Validation backend URL must be an http loopback URL with a port."))
    }

    func testManifestRejectsSessionRootOutsideOwnedBase() throws {
        let manifestURL = try writeManifest(sessionRoot: temporaryDirectory.appendingPathComponent("outside"))

        let result = BasilRuntimeProfile.bootstrap(
            arguments: ["BasilClient", "--validation-session", manifestURL.path],
            sessionBaseURL: sessionBaseURL
        )

        XCTAssertEqual(result, .failure("Validation launch rejected: Validation session root is outside the owned sessions directory."))
    }

    func testManifestRejectsWrongSchemaVersion() throws {
        let manifestURL = try writeManifest(schemaVersion: 99)

        let result = BasilRuntimeProfile.bootstrap(
            arguments: ["BasilClient", "--validation-session", manifestURL.path],
            sessionBaseURL: sessionBaseURL
        )

        XCTAssertEqual(result, .failure("Validation launch rejected: Unsupported validation manifest schema version 99."))
    }

    func testValidationDefaultsAndCredentialKeysDoNotUseNormalNamespaces() throws {
        let manifestURL = try writeManifest()
        let result = BasilRuntimeProfile.bootstrap(
            arguments: ["BasilClient", "--validation-session", manifestURL.path],
            sessionBaseURL: sessionBaseURL
        )
        guard case .success(let profile) = result else {
            return XCTFail("Expected a validation profile")
        }
        BasilRuntimeProfile.install(profile)
        let key = "BasilRuntimeProfileTests.validationValue"
        UserDefaults.standard.removeObject(forKey: key)
        BasilRuntimeProfile.userDefaults.set("validation", forKey: key)

        XCTAssertEqual(BasilRuntimeProfile.userDefaults.string(forKey: key), "validation")
        XCTAssertNil(UserDefaults.standard.string(forKey: key))
        XCTAssertEqual(
            BasilRuntimeProfile.credentialKey("com.basil.accessToken"),
            "com.stratten.basil.validation.live-preview.com.basil.accessToken"
        )
        BasilRuntimeProfile.userDefaults.removePersistentDomain(forName: "com.stratten.basil.validation.live-preview.")
    }

    private func writeManifest(
        schemaVersion: Int = ValidationSessionManifest.supportedSchemaVersion,
        sessionRoot: URL? = nil,
        backendURL: URL = URL(string: "http://127.0.0.1:8765")!
    ) throws -> URL {
        let resolvedSessionRoot = sessionRoot ?? sessionBaseURL.appendingPathComponent("live-preview")
        try FileManager.default.createDirectory(at: resolvedSessionRoot, withIntermediateDirectories: true)
        let manifestURL = resolvedSessionRoot.appendingPathComponent("session.json")
        let manifest = ValidationSessionManifest(
            schemaVersion: schemaVersion,
            sessionID: "live-preview",
            sessionRoot: resolvedSessionRoot,
            backendURL: backendURL,
            fixtureManifestURL: resolvedSessionRoot.appendingPathComponent("fixtures.json"),
            probeURL: resolvedSessionRoot.appendingPathComponent("probe.json"),
            credentialNamespace: "com.stratten.basil.validation.live-preview.",
            createdAt: Date(timeIntervalSince1970: 0),
            mode: .developerLocal
        )
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(manifest).write(to: manifestURL)
        return manifestURL
    }
}
