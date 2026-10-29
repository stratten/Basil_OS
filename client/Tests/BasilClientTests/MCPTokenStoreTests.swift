import XCTest
@testable import BasilClient

@MainActor
final class MCPTokenStoreTests: XCTestCase {
    private final class FakeKeychain {
        var items: [String: String] = [:]
        var reads: [String] = []
        var deletes: [String] = []
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

    private func makeStore(_ keychain: FakeKeychain) -> MCPTokenStore {
        MCPTokenStore(
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            deleteItem: { keychain.delete($0) },
            itemExists: { keychain.exists($0) }
        )
    }

    private var vaultKey: String { BasilRuntimeProfile.credentialKey("com.basil.mcpTokenVault") }
    private func accessKey(_ id: String) -> String { BasilRuntimeProfile.credentialKey("com.basil.mcpToken.\(id)") }
    private func refreshKey(_ id: String) -> String { BasilRuntimeProfile.credentialKey("com.basil.mcpRefreshToken.\(id)") }

    func testStoringAConnectionKeepsTheAccountAndProviderKeysInTheSharedVault() throws {
        let keychain = FakeKeychain()
        let vault = CredentialVault(
            vaultKey: vaultKey,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            itemExists: { keychain.exists($0) }
        )
        try vault.update {
            $0.account = StoredAccountCredentials(accessToken: "acct", refreshToken: "acct-r", hasPaymentMethod: true)
            $0.providerKeys = ["openai": "sk-test"]
        }
        let store = MCPTokenStore(
            vault: vault,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            deleteItem: { keychain.delete($0) }
        )

        try store.store(connectionId: "c", accessToken: "a", refreshToken: "r")

        let saved = try JSONDecoder().decode(
            CredentialVault.Contents.self,
            from: Data(try XCTUnwrap(keychain.items[vaultKey]).utf8)
        )
        XCTAssertEqual(saved.version, 2)
        XCTAssertEqual(saved.account?.accessToken, "acct")
        XCTAssertEqual(saved.providerKeys, ["openai": "sk-test"])
        XCTAssertEqual(saved.connections["c"], CredentialVault.ConnectionEntry(access: "a", refresh: "r"))
        XCTAssertEqual(Set(keychain.items.keys), [vaultKey])
    }

    func testStoringWritesOnlyTheVaultAndNeverTheAccountItem() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        try store.store(connectionId: "gmail-1", accessToken: "a", refreshToken: "r")

        XCTAssertEqual(Set(keychain.items.keys), [vaultKey])
        XCTAssertFalse(keychain.items.keys.contains(BasilRuntimeProfile.credentialKey("com.basil.account")))
    }

    func testStoredTokensSurviveANewProcessAndAreReadWithOneKeychainRead() throws {
        let keychain = FakeKeychain()
        try makeStore(keychain).store(connectionId: "c", accessToken: "a", refreshToken: "r")
        keychain.reads.removeAll()

        let relaunched = makeStore(keychain)

        XCTAssertEqual(relaunched.accessToken(connectionId: "c"), "a")
        XCTAssertEqual(relaunched.refreshToken(connectionId: "c"), "r")
        XCTAssertEqual(keychain.reads, [vaultKey])
    }

    func testEveryConnectionIsAnsweredFromOneVaultReadSoOnePromptCoversAllOfThem() throws {
        let keychain = FakeKeychain()
        let writer = makeStore(keychain)
        try writer.store(connectionId: "gmail", accessToken: "ga", refreshToken: "gr")
        try writer.store(connectionId: "github", accessToken: "ha")
        try writer.store(connectionId: "linear", accessToken: "la", refreshToken: "lr")
        keychain.reads.removeAll()

        let relaunched = makeStore(keychain)
        XCTAssertFalse(relaunched.hasCachedAccessToken(connectionId: "gmail"))
        XCTAssertEqual(relaunched.accessToken(connectionId: "gmail"), "ga")
        XCTAssertTrue(relaunched.hasCachedAccessToken(connectionId: "github"))
        XCTAssertEqual(relaunched.accessToken(connectionId: "github"), "ha")
        XCTAssertEqual(relaunched.accessToken(connectionId: "linear"), "la")
        XCTAssertEqual(relaunched.refreshToken(connectionId: "linear"), "lr")
        XCTAssertEqual(relaunched.refreshToken(connectionId: "gmail"), "gr")

        XCTAssertEqual(keychain.reads, [vaultKey])
    }

    func testRefreshTokenIsAnsweredFromMemoryOnceTheAccessTokenWasRead() throws {
        let keychain = FakeKeychain()
        try makeStore(keychain).store(connectionId: "c", accessToken: "a", refreshToken: "r")
        let relaunched = makeStore(keychain)

        _ = relaunched.accessToken(connectionId: "c")

        XCTAssertTrue(relaunched.hasCachedRefreshToken(connectionId: "c"))
    }

    func testMissingTokenIsNilAndIsNotCached() {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        XCTAssertNil(store.accessToken(connectionId: "none"))
        XCTAssertFalse(store.hasCachedAccessToken(connectionId: "none"))
        XCTAssertNil(store.refreshToken(connectionId: "none"))
        XCTAssertTrue(keychain.items.isEmpty)
    }

    func testStoringWithoutARefreshTokenKeepsTheExistingOneUnlessReplacing() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)
        try store.store(connectionId: "c", accessToken: "a1", refreshToken: "r1")

        try store.store(connectionId: "c", accessToken: "a2")
        XCTAssertEqual(store.refreshToken(connectionId: "c"), "r1")
        XCTAssertEqual(store.accessToken(connectionId: "c"), "a2")

        try store.store(connectionId: "c", accessToken: "a3", replacingRefreshToken: true)
        XCTAssertNil(store.refreshToken(connectionId: "c"))
        XCTAssertEqual(store.accessToken(connectionId: "c"), "a3")

        let relaunched = makeStore(keychain)
        XCTAssertNil(relaunched.refreshToken(connectionId: "c"))
        XCTAssertEqual(relaunched.accessToken(connectionId: "c"), "a3")
    }

    func testDeleteRemovesOnlyThatConnectionAndKeepsTheOthers() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)
        try store.store(connectionId: "c", accessToken: "a", refreshToken: "r")
        try store.store(connectionId: "other", accessToken: "oa")

        store.delete(connectionId: "c")

        XCTAssertFalse(store.hasCachedAccessToken(connectionId: "c"))
        XCTAssertNil(store.accessToken(connectionId: "c"))
        XCTAssertNil(store.refreshToken(connectionId: "c"))
        let relaunched = makeStore(keychain)
        XCTAssertNil(relaunched.accessToken(connectionId: "c"))
        XCTAssertEqual(relaunched.accessToken(connectionId: "other"), "oa")
    }

    func testDeleteAlsoRemovesTheConnectionsEarlierPerConnectionItemsAndNothingElse() {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        store.delete(connectionId: "c")

        XCTAssertEqual(Set(keychain.deletes), [accessKey("c"), refreshKey("c")])
        XCTAssertFalse(keychain.deletes.contains(vaultKey))
    }

    func testFailedWriteThrowsAndDoesNotPoisonTheCache() {
        let keychain = FakeKeychain()
        keychain.failWrites = true
        let store = makeStore(keychain)

        XCTAssertThrowsError(try store.store(connectionId: "c", accessToken: "a"))
        XCTAssertFalse(store.hasCachedAccessToken(connectionId: "c"))
        XCTAssertNil(store.accessToken(connectionId: "c"))
    }

    func testRewrittenTokensReplaceTheCachedOnesAfterRotation() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)
        try store.store(connectionId: "c", accessToken: "old", refreshToken: "r")
        keychain.reads.removeAll()

        try store.store(connectionId: "c", accessToken: "new", refreshToken: "r2", replacingRefreshToken: true)

        XCTAssertEqual(store.accessToken(connectionId: "c"), "new")
        XCTAssertEqual(store.refreshToken(connectionId: "c"), "r2")
        XCTAssertTrue(keychain.reads.isEmpty)
        XCTAssertEqual(makeStore(keychain).accessToken(connectionId: "c"), "new")
    }

    func testEarlierPerConnectionItemsAreMovedIntoTheVaultAndRemoved() {
        let keychain = FakeKeychain()
        keychain.items[accessKey("c")] = "a"
        keychain.items[refreshKey("c")] = "r"
        let store = makeStore(keychain)

        XCTAssertEqual(store.accessToken(connectionId: "c"), "a")
        XCTAssertEqual(store.refreshToken(connectionId: "c"), "r")

        XCTAssertEqual(Set(keychain.items.keys), [vaultKey])
        keychain.reads.removeAll()
        let relaunched = makeStore(keychain)
        XCTAssertEqual(relaunched.accessToken(connectionId: "c"), "a")
        XCTAssertEqual(relaunched.refreshToken(connectionId: "c"), "r")
        XCTAssertEqual(keychain.reads, [vaultKey])
    }

    func testMigratingOneConnectionLeavesAnotherConnectionsEarlierItemsForItsOwnFirstUse() {
        let keychain = FakeKeychain()
        keychain.items[accessKey("one")] = "1a"
        keychain.items[accessKey("two")] = "2a"
        let store = makeStore(keychain)

        XCTAssertEqual(store.accessToken(connectionId: "one"), "1a")

        XCTAssertEqual(keychain.items[accessKey("two")], "2a")
        XCTAssertNil(keychain.items[accessKey("one")])
        XCTAssertEqual(store.accessToken(connectionId: "two"), "2a")
        XCTAssertEqual(Set(keychain.items.keys), [vaultKey])
    }

    func testAFailedVaultWriteDuringMigrationKeepsTheEarlierItemsAndStillServesTheToken() {
        let keychain = FakeKeychain()
        keychain.items[accessKey("c")] = "a"
        keychain.items[refreshKey("c")] = "r"
        keychain.failWrites = true
        let store = makeStore(keychain)

        XCTAssertEqual(store.accessToken(connectionId: "c"), "a")
        XCTAssertEqual(store.refreshToken(connectionId: "c"), "r")

        XCTAssertEqual(keychain.items[accessKey("c")], "a")
        XCTAssertEqual(keychain.items[refreshKey("c")], "r")
        XCTAssertNil(keychain.items[vaultKey])
    }

    func testAnUnreadableVaultIsNeverOverwrittenAndTheEarlierItemsAreUsedInstead() throws {
        let keychain = FakeKeychain()
        let original = #"{"version":1,"connections":{"kept":{"access":"ka"}}}"#
        keychain.items[vaultKey] = original
        keychain.unreadableKeys = [vaultKey]
        keychain.items[accessKey("legacy")] = "la"
        let store = makeStore(keychain)

        XCTAssertEqual(store.accessToken(connectionId: "legacy"), "la")
        try store.store(connectionId: "new", accessToken: "na")

        XCTAssertEqual(keychain.items[vaultKey], original)
        XCTAssertEqual(keychain.items[accessKey("new")], "na")
        XCTAssertEqual(store.accessToken(connectionId: "new"), "na")
        XCTAssertFalse(store.hasCachedAccessToken(connectionId: "new"))
    }

    func testAVaultThatCannotBeDecodedIsNeverOverwritten() throws {
        let keychain = FakeKeychain()
        keychain.items[vaultKey] = "not json"
        let store = makeStore(keychain)

        try store.store(connectionId: "c", accessToken: "a")

        XCTAssertEqual(keychain.items[vaultKey], "not json")
        XCTAssertEqual(keychain.items[accessKey("c")], "a")
    }

    func testTheVaultIsReadAgainAfterAnUnreadableAttemptSoApprovingLaterWorks() throws {
        let keychain = FakeKeychain()
        try makeStore(keychain).store(connectionId: "c", accessToken: "a")
        keychain.unreadableKeys = [vaultKey]
        let store = makeStore(keychain)

        XCTAssertNil(store.accessToken(connectionId: "c"))
        keychain.unreadableKeys = []

        XCTAssertEqual(store.accessToken(connectionId: "c"), "a")
    }
}
