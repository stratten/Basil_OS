import XCTest
@testable import BasilClient

@MainActor
final class VaultAccountItemsTests: XCTestCase {
    private final class FakeKeychain {
        var items: [String: String] = [:]
        var reads: [String] = []
        var deletes: [String] = []
        var failWrites = false
        var unreadableKeys: Set<String> = []

        func read(_ key: String) -> String? {
            reads.append(key)
            if unreadableKeys.contains(key) { return nil }
            return items[key]
        }

        func write(_ key: String, _ value: String) throws {
            if failWrites { throw MCPTokenStoreError.keychainWriteFailed(status: -1) }
            items[key] = value
        }

        func delete(_ key: String) {
            deletes.append(key)
            items.removeValue(forKey: key)
        }

        func exists(_ key: String) -> Bool {
            items[key] != nil || unreadableKeys.contains(key)
        }
    }

    private let vaultKey = "test.vault"
    private let accountKey = "test.account"
    private let credentials = StoredAccountCredentials(accessToken: "a", refreshToken: "r", hasPaymentMethod: true)

    private func makeVault(_ keychain: FakeKeychain) -> CredentialVault {
        CredentialVault(
            vaultKey: vaultKey,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            itemExists: { keychain.exists($0) }
        )
    }

    private func makeItems(_ keychain: FakeKeychain, vault: CredentialVault? = nil) -> VaultAccountItems {
        VaultAccountItems(
            vault: vault ?? makeVault(keychain),
            accountKey: accountKey,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            deleteItem: { keychain.delete($0) }
        )
    }

    private func accountJSON() throws -> String {
        // JSONEncoder does not promise a key order, so two encodings of the same value can differ as text; sorted keys keep the comparisons below deterministic.
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return String(decoding: try encoder.encode(credentials), as: UTF8.self)
    }

    private func vaultContents(_ keychain: FakeKeychain) throws -> CredentialVault.Contents {
        let text = try XCTUnwrap(keychain.items[vaultKey])
        return try JSONDecoder().decode(CredentialVault.Contents.self, from: Data(text.utf8))
    }

    func testWritingTheAccountStoresItInTheVaultAndLeavesNoStandaloneItem() throws {
        let keychain = FakeKeychain()

        try makeItems(keychain).write(key: accountKey, value: try accountJSON())

        XCTAssertEqual(try vaultContents(keychain).account, credentials)
        XCTAssertNil(keychain.items[accountKey])
    }

    func testReadingTheAccountIsAnsweredFromTheVaultWithOneKeychainRead() throws {
        let keychain = FakeKeychain()
        try makeItems(keychain).write(key: accountKey, value: try accountJSON())
        keychain.reads.removeAll()

        let relaunched = makeItems(keychain)
        let raw = try XCTUnwrap(relaunched.read(key: accountKey))

        XCTAssertEqual(try JSONDecoder().decode(StoredAccountCredentials.self, from: Data(raw.utf8)), credentials)
        XCTAssertEqual(keychain.reads, [vaultKey])
    }

    func testAStandaloneAccountItemIsMovedIntoTheVault() throws {
        let keychain = FakeKeychain()
        keychain.items[accountKey] = try accountJSON()

        let raw = makeItems(keychain).read(key: accountKey)

        XCTAssertEqual(raw, try accountJSON())
        XCTAssertEqual(try vaultContents(keychain).account, credentials)
        XCTAssertNil(keychain.items[accountKey])
        XCTAssertTrue(keychain.deletes.contains(accountKey))
    }

    func testAStandaloneAccountItemIsKeptWhenTheVaultCannotBeSaved() throws {
        let keychain = FakeKeychain()
        keychain.items[accountKey] = try accountJSON()
        keychain.failWrites = true

        let raw = makeItems(keychain).read(key: accountKey)

        XCTAssertEqual(raw, try accountJSON())
        XCTAssertEqual(keychain.items[accountKey], try accountJSON())
        XCTAssertNil(keychain.items[vaultKey])
    }

    func testAStandaloneAccountItemStillAnswersWhenTheVaultIsUnreadable() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "existing secret data"
        keychain.unreadableKeys = [vaultKey]
        keychain.items[accountKey] = try accountJSON()

        let raw = makeItems(keychain).read(key: accountKey)

        XCTAssertEqual(raw, try accountJSON())
        XCTAssertEqual(keychain.items[accountKey], try accountJSON())
        XCTAssertEqual(keychain.items[vaultKey], "existing secret data")
    }

    func testSigningOutClearsTheAccountButKeepsEveryOtherSecretInTheVault() throws {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)
        try vault.update {
            $0.account = credentials
            $0.providerKeys = ["openai": "sk-test"]
            $0.connections = ["c": CredentialVault.ConnectionEntry(access: "a", refresh: "r")]
        }

        makeItems(keychain, vault: vault).delete(key: accountKey)

        let saved = try vaultContents(keychain)
        XCTAssertNil(saved.account)
        XCTAssertEqual(saved.providerKeys, ["openai": "sk-test"])
        XCTAssertEqual(saved.connections["c"], CredentialVault.ConnectionEntry(access: "a", refresh: "r"))
    }

    func testTheOlderSeparateAccountKeysPassStraightThrough() throws {
        let keychain = FakeKeychain()
        let items = makeItems(keychain)

        try items.write(key: "test.legacy.accessToken", value: "legacy")

        XCTAssertEqual(keychain.items["test.legacy.accessToken"], "legacy")
        XCTAssertNil(keychain.items[vaultKey])
        XCTAssertEqual(items.read(key: "test.legacy.accessToken"), "legacy")
        items.delete(key: "test.legacy.accessToken")
        XCTAssertNil(keychain.items["test.legacy.accessToken"])
    }

    func testTheAccountCredentialStoreRoundTripsThroughTheVault() throws {
        let keychain = FakeKeychain()
        let vault = makeVault(keychain)
        func makeStore() -> AccountCredentialStore {
            let items = makeItems(keychain, vault: vault)
            return AccountCredentialStore(
                accountKey: accountKey,
                legacyAccessTokenKey: "test.legacy.accessToken",
                legacyRefreshTokenKey: "test.legacy.refreshToken",
                legacyPaymentMethodKey: "test.legacy.hasPaymentMethod",
                readItem: { items.read(key: $0) },
                writeItem: { try items.write(key: $0, value: $1) },
                deleteItem: { items.delete(key: $0) }
            )
        }

        try makeStore().save(accessToken: "a", refreshToken: "r", hasPaymentMethod: true)

        XCTAssertEqual(makeStore().load(), credentials)
        XCTAssertEqual(Set(keychain.items.keys), [vaultKey])

        let signOut = makeStore()
        signOut.clear()
        XCTAssertNil(makeStore().load())
        XCTAssertNil(try vaultContents(keychain).account)
    }
}
