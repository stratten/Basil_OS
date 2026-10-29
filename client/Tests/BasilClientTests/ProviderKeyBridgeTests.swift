import XCTest
@testable import BasilClient

@MainActor
final class ProviderKeyBridgeTests: XCTestCase {
    private final class FakeKeychain {
        var items: [String: String] = [:]
        var writes: [String] = []
        var failWrites = false
        var unreadableKeys: Set<String> = []

        func read(_ key: String) -> String? {
            if unreadableKeys.contains(key) { return nil }
            return items[key]
        }

        func write(_ key: String, _ value: String) throws {
            if failWrites { throw MCPTokenStoreError.keychainWriteFailed(status: -1) }
            writes.append(key)
            items[key] = value
        }

        func exists(_ key: String) -> Bool {
            items[key] != nil || unreadableKeys.contains(key)
        }
    }

    private let vaultKey = "test.vault"

    private func makeVault(_ keychain: FakeKeychain) -> CredentialVault {
        CredentialVault(
            vaultKey: vaultKey,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            itemExists: { keychain.exists($0) }
        )
    }

    private func decode(_ text: String) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
    }

    private func storedKeys(_ keychain: FakeKeychain) throws -> [String: String] {
        let text = try XCTUnwrap(keychain.items[vaultKey])
        return try JSONDecoder().decode(CredentialVault.Contents.self, from: Data(text.utf8)).providerKeys
    }

    func testTheSnapshotCarriesEveryProviderKeyWithTheRequestsCorrelationId() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":2,"providerKeys":{"openai":"sk-a","custom_x":"k-b"}}"#
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeysRequest(
            ["type": "provider_keys_request", "correlation_id": "c1"],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )

        XCTAssertEqual(sent.count, 1)
        let reply = try decode(sent[0])
        XCTAssertEqual(reply["type"] as? String, "provider_keys_snapshot")
        XCTAssertEqual(reply["correlation_id"] as? String, "c1")
        XCTAssertEqual(reply["status"] as? String, "ok")
        XCTAssertEqual(reply["keys"] as? [String: String], ["openai": "sk-a", "custom_x": "k-b"])
    }

    func testAnUnreadableVaultReportsUnavailableAndIsLeftUntouched() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "existing secret data"
        keychain.unreadableKeys = [vaultKey]
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeysRequest(
            ["correlation_id": "c1-unavailable"],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )

        let reply = try decode(try XCTUnwrap(sent.first))
        XCTAssertEqual(reply["status"] as? String, "unavailable")
        XCTAssertEqual((reply["keys"] as? [String: String])?.count, 0)
        XCTAssertEqual(keychain.items[vaultKey], "existing secret data")
        XCTAssertTrue(keychain.writes.isEmpty)
    }

    func testARepeatedSnapshotRequestIsAnsweredOnlyOnce() {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":2,"providerKeys":{"openai":"sk-a"}}"#
        var sent: [String] = []

        for _ in 0..<3 {
            WebSocketService_ProviderKeys.handleKeysRequest(
                ["correlation_id": "c1-repeat"],
                vault: makeVault(keychain),
                send: { sent.append($0) }
            )
        }

        XCTAssertEqual(sent.count, 1)
    }

    func testRequestsWithoutACorrelationIdAreIgnored() {
        let keychain = FakeKeychain()
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeysRequest([:], vault: makeVault(keychain), send: { sent.append($0) })
        WebSocketService_ProviderKeys.handleKeyStore(["name": "openai", "value": "sk"], vault: makeVault(keychain), send: { sent.append($0) })
        WebSocketService_ProviderKeys.handleKeyDelete(["name": "openai"], vault: makeVault(keychain), send: { sent.append($0) })

        XCTAssertTrue(sent.isEmpty)
        XCTAssertTrue(keychain.writes.isEmpty)
    }

    func testStoringAKeyWritesTheVaultAndAcknowledges() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":2,"connections":{"c":{"access":"a","refresh":"r"}}}"#
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyStore(
            ["correlation_id": "c2", "name": "openai", "value": "sk-test"],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )

        let reply = try decode(try XCTUnwrap(sent.first))
        XCTAssertEqual(reply["type"] as? String, "provider_key_result")
        XCTAssertEqual(reply["correlation_id"] as? String, "c2")
        XCTAssertEqual(reply["ok"] as? Bool, true)
        XCTAssertEqual(try storedKeys(keychain), ["openai": "sk-test"])
        XCTAssertTrue(try XCTUnwrap(keychain.items[vaultKey]).contains("\"c\""))
    }

    func testStoringIntoAnUnreadableVaultFailsAndLeavesItUntouched() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "existing secret data"
        keychain.unreadableKeys = [vaultKey]
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyStore(
            ["correlation_id": "c3", "name": "openai", "value": "sk-test"],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )

        let reply = try decode(try XCTUnwrap(sent.first))
        XCTAssertEqual(reply["ok"] as? Bool, false)
        XCTAssertEqual(reply["error"] as? String, "vault_unreadable")
        XCTAssertEqual(keychain.items[vaultKey], "existing secret data")
    }

    func testAFailedKeychainWriteIsReportedAsWriteFailed() throws {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)
        XCTAssertNotNil(vault.load())
        keychain.failWrites = true
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyStore(
            ["correlation_id": "c4", "name": "openai", "value": "sk-test"],
            vault: vault,
            send: { sent.append($0) }
        )

        let reply = try decode(try XCTUnwrap(sent.first))
        XCTAssertEqual(reply["ok"] as? Bool, false)
        XCTAssertEqual(reply["error"] as? String, "write_failed")
    }

    func testAnEmptyNameOrValueIsRejectedWithoutWriting() throws {
        let keychain = FakeKeychain()
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyStore(
            ["correlation_id": "c5", "name": "", "value": "sk-test"],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )
        WebSocketService_ProviderKeys.handleKeyStore(
            ["correlation_id": "c6", "name": "openai", "value": ""],
            vault: makeVault(keychain),
            send: { sent.append($0) }
        )

        XCTAssertEqual(try sent.map { try decode($0)["error"] as? String }, ["bad_request", "bad_request"])
        XCTAssertTrue(keychain.writes.isEmpty)
    }

    func testDeletingAKeyRemovesOnlyThatKeyAndAnAbsentKeyStillSucceeds() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":2,"providerKeys":{"openai":"sk-a","google":"g-b"}}"#
        let vault = makeVault(keychain)
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyDelete(
            ["correlation_id": "c7", "name": "openai"], vault: vault, send: { sent.append($0) }
        )
        WebSocketService_ProviderKeys.handleKeyDelete(
            ["correlation_id": "c8", "name": "never-stored"], vault: vault, send: { sent.append($0) }
        )

        XCTAssertEqual(try sent.map { try decode($0)["ok"] as? Bool }, [true, true])
        XCTAssertEqual(try storedKeys(keychain), ["google": "g-b"])
        XCTAssertEqual(keychain.writes.count, 1)
    }

    func testDeletingFromAnUnreadableVaultFails() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "existing secret data"
        keychain.unreadableKeys = [vaultKey]
        var sent: [String] = []

        WebSocketService_ProviderKeys.handleKeyDelete(
            ["correlation_id": "c9", "name": "openai"], vault: makeVault(keychain), send: { sent.append($0) }
        )

        let reply = try decode(try XCTUnwrap(sent.first))
        XCTAssertEqual(reply["ok"] as? Bool, false)
        XCTAssertEqual(reply["error"] as? String, "vault_unreadable")
        XCTAssertEqual(keychain.items[vaultKey], "existing secret data")
    }
}
