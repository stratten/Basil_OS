import XCTest
@testable import BasilClient

final class AccountCredentialStoreTests: XCTestCase {
    private final class FakeKeychain {
        var items: [String: String] = [:]
        var reads: [String] = []
        var failWrites = false

        func read(_ key: String) -> String? {
            reads.append(key)
            return items[key]
        }

        func write(_ key: String, _ value: String) throws {
            if failWrites { throw AuthError.networkError("write failed") }
            items[key] = value
        }

        func delete(_ key: String) {
            items.removeValue(forKey: key)
        }
    }

    private let account = "acct"
    private let legacyAccess = "legacy.access"
    private let legacyRefresh = "legacy.refresh"
    private let legacyPayment = "legacy.payment"

    private func makeStore(_ keychain: FakeKeychain) -> AccountCredentialStore {
        AccountCredentialStore(
            accountKey: account,
            legacyAccessTokenKey: legacyAccess,
            legacyRefreshTokenKey: legacyRefresh,
            legacyPaymentMethodKey: legacyPayment,
            readItem: { keychain.read($0) },
            writeItem: { try keychain.write($0, $1) },
            deleteItem: { keychain.delete($0) }
        )
    }

    func testSavingWritesOneItemThatHoldsEveryValue() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        try store.save(accessToken: "a", refreshToken: "r", hasPaymentMethod: true)

        XCTAssertEqual(Set(keychain.items.keys), [account])
        let restored = makeStore(keychain).load()
        XCTAssertEqual(restored, StoredAccountCredentials(accessToken: "a", refreshToken: "r", hasPaymentMethod: true))
    }

    func testOneLoadReadsTheKeychainOnceNoMatterHowManyValuesAreAskedFor() throws {
        let keychain = FakeKeychain()
        try makeStore(keychain).save(accessToken: "a", refreshToken: "r", hasPaymentMethod: false)
        keychain.reads.removeAll()
        let store = makeStore(keychain)

        _ = store.load()?.accessToken
        _ = store.load()?.refreshToken
        _ = store.load()?.hasPaymentMethod

        XCTAssertEqual(keychain.reads, [account])
    }

    func testAnEmptyKeychainIsOnlyReadOnceToo() {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        XCTAssertNil(store.load())
        let readsAfterFirstLoad = keychain.reads.count
        XCTAssertNil(store.load())

        XCTAssertEqual(keychain.reads.count, readsAfterFirstLoad)
        XCTAssertTrue(store.hasLoaded)
    }

    func testOldSeparateItemsAreMigratedIntoOneItemAndRemoved() {
        let keychain = FakeKeychain()
        keychain.items = [legacyAccess: "old-a", legacyRefresh: "old-r", legacyPayment: "true"]
        let store = makeStore(keychain)

        let loaded = store.load()

        XCTAssertEqual(loaded, StoredAccountCredentials(accessToken: "old-a", refreshToken: "old-r", hasPaymentMethod: true))
        XCTAssertEqual(Set(keychain.items.keys), [account])
        keychain.reads.removeAll()
        _ = makeStore(keychain).load()
        XCTAssertEqual(keychain.reads, [account])
    }

    func testMigrationKeepsTheOldItemsWhenTheNewItemCannotBeWritten() {
        let keychain = FakeKeychain()
        keychain.items = [legacyAccess: "old-a", legacyRefresh: "old-r"]
        keychain.failWrites = true
        let store = makeStore(keychain)

        XCTAssertEqual(store.load()?.accessToken, "old-a")
        XCTAssertEqual(Set(keychain.items.keys), [legacyAccess, legacyRefresh])
    }

    func testAPartialOldLayoutIsNotTreatedAsSignedIn() {
        let keychain = FakeKeychain()
        keychain.items = [legacyAccess: "old-a"]

        XCTAssertNil(makeStore(keychain).load())
    }

    func testUpdatingThePaymentFlagKeepsTheTokensAndPersists() throws {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)
        try store.save(accessToken: "a", refreshToken: "r", hasPaymentMethod: false)

        store.updateHasPaymentMethod(true)

        XCTAssertEqual(store.load(), StoredAccountCredentials(accessToken: "a", refreshToken: "r", hasPaymentMethod: true))
        XCTAssertEqual(makeStore(keychain).load()?.hasPaymentMethod, true)
        XCTAssertEqual(Set(keychain.items.keys), [account])
    }

    func testUpdatingThePaymentFlagWithNobodySignedInStoresNothing() {
        let keychain = FakeKeychain()
        let store = makeStore(keychain)

        store.updateHasPaymentMethod(true)

        XCTAssertTrue(keychain.items.isEmpty)
        XCTAssertNil(store.load())
    }

    func testClearRemovesTheItemAndAnyOldItemsAndForgetsTheCache() throws {
        let keychain = FakeKeychain()
        keychain.items = [legacyAccess: "x", legacyRefresh: "y", legacyPayment: "true"]
        let store = makeStore(keychain)
        try store.save(accessToken: "a", refreshToken: "r", hasPaymentMethod: true)

        store.clear()

        XCTAssertTrue(keychain.items.isEmpty)
        XCTAssertNil(store.load())
    }

    func testAnUnreadableAccountItemFallsBackToTheOldLayout() {
        let keychain = FakeKeychain()
        keychain.items = [account: "not json", legacyAccess: "old-a", legacyRefresh: "old-r"]

        XCTAssertEqual(makeStore(keychain).load()?.refreshToken, "old-r")
    }
}
