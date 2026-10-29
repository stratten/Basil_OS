import XCTest
@testable import BasilClient

@MainActor
final class CredentialVaultTests: XCTestCase {
    private final class FakeKeychain {
        var items: [String: String] = [:]
        var reads: [String] = []
        var writes: [String] = []
        var failWrites = false
        /// Keys that exist but whose secret cannot be read, as when the user chooses Deny.
        var unreadableKeys: Set<String> = []

        func read(_ key: String) -> String? {
            reads.append(key)
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

    private func savedContents(_ keychain: FakeKeychain) throws -> CredentialVault.Contents {
        let text = try XCTUnwrap(keychain.items[vaultKey])
        return try JSONDecoder().decode(CredentialVault.Contents.self, from: Data(text.utf8))
    }

    func testAnEmptyKeychainLoadsAnEmptyVaultAndIsOnlyReadOnce() {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)

        XCTAssertEqual(vault.load(), CredentialVault.Contents())
        XCTAssertEqual(vault.load(), CredentialVault.Contents())
        XCTAssertEqual(keychain.reads, [vaultKey])
        XCTAssertTrue(keychain.items.isEmpty)
    }

    func testAVersionOneVaultStillDecodesAndKeepsItsConnections() {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":1,"connections":{"gmail-1":{"access":"a","refresh":"r"}}}"#

        let contents = makeVault(keychain).load()

        XCTAssertEqual(contents?.version, 1)
        XCTAssertEqual(contents?.connections["gmail-1"], CredentialVault.ConnectionEntry(access: "a", refresh: "r"))
        XCTAssertNil(contents?.account)
        XCTAssertEqual(contents?.providerKeys, [:])
    }

    func testUpdatingStampsVersionTwoAndPreservesEveryOtherField() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":1,"connections":{"gmail-1":{"access":"a","refresh":"r"}}}"#
        let vault = makeVault(keychain)

        try vault.update {
            $0.providerKeys["openai"] = "sk-test"
            $0.account = StoredAccountCredentials(accessToken: "acct", refreshToken: "acct-r", hasPaymentMethod: true)
        }

        let saved = try savedContents(keychain)
        XCTAssertEqual(saved.version, 2)
        XCTAssertEqual(saved.connections["gmail-1"], CredentialVault.ConnectionEntry(access: "a", refresh: "r"))
        XCTAssertEqual(saved.providerKeys, ["openai": "sk-test"])
        XCTAssertEqual(saved.account?.accessToken, "acct")
        XCTAssertEqual(vault.cachedContents, saved)
    }

    func testAnUnreadableVaultIsNeverOverwritten() {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "existing secret data"
        keychain.unreadableKeys = [vaultKey]
        let vault = makeVault(keychain)

        XCTAssertNil(vault.load())
        XCTAssertThrowsError(try vault.update { $0.providerKeys["openai"] = "sk-test" }) { error in
            XCTAssertEqual(error as? CredentialVaultError, .unreadable)
        }
        XCTAssertEqual(keychain.items[vaultKey], "existing secret data")
        XCTAssertTrue(keychain.writes.isEmpty)
        XCTAssertNil(vault.cachedContents)
    }

    func testAnUndecodableVaultIsNeverOverwritten() {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "{not json"
        let vault = makeVault(keychain)

        XCTAssertNil(vault.load())
        XCTAssertThrowsError(try vault.update { $0.providerKeys["openai"] = "sk-test" })
        XCTAssertEqual(keychain.items[vaultKey], "{not json")
        XCTAssertTrue(keychain.writes.isEmpty)
    }

    func testAnUnreadableVaultIsReadAgainOnTheNextRequest() {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = #"{"version":2,"providerKeys":{"openai":"sk-test"}}"#
        keychain.unreadableKeys = [vaultKey]
        let vault = makeVault(keychain)
        XCTAssertNil(vault.load())

        keychain.unreadableKeys = []

        XCTAssertEqual(vault.load()?.providerKeys, ["openai": "sk-test"])
        XCTAssertEqual(keychain.reads, [vaultKey, vaultKey])
    }

    func testAFailedWriteLeavesTheCachedVaultUnchanged() {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)
        XCTAssertNotNil(vault.load())
        keychain.failWrites = true

        XCTAssertThrowsError(try vault.update { $0.providerKeys["openai"] = "sk-test" })

        XCTAssertEqual(vault.cachedContents?.providerKeys, [:])
        XCTAssertTrue(keychain.items.isEmpty)
    }

    func testRememberingChangesOnlyTheInMemoryCopy() {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)

        vault.remember { $0.connections["c"] = CredentialVault.ConnectionEntry(access: "a", refresh: nil) }

        XCTAssertEqual(vault.cachedContents?.connections["c"]?.access, "a")
        XCTAssertTrue(keychain.items.isEmpty)
    }
}
