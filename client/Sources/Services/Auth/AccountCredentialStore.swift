import Foundation

/// The Basil account's sign-in credentials, kept together so they live in one Keychain item and one read answers for all of them.
struct StoredAccountCredentials: Codable, Equatable {
    var accessToken: String
    var refreshToken: String
    var hasPaymentMethod: Bool
}

/// Stores the account's access token, refresh token, and payment flag as a single Keychain item.
///
/// Before this existed each value was its own item, and on builds whose code signature changes with every rebuild macOS asks for permission once per item, so one sign-in read produced several prompts for the same account. One item means one prompt. Items written by the old layout are read once, rewritten into the single item, and deleted.
///
/// The first ``load()`` is the only call that reads the Keychain; the result, including "nothing stored", is then held in memory for the life of the process, so asking again never prompts.
final class AccountCredentialStore {
    typealias ReadItem = (_ key: String) -> String?
    typealias WriteItem = (_ key: String, _ value: String) throws -> Void
    typealias DeleteItem = (_ key: String) -> Void

    private let accountKey: String
    private let legacyAccessTokenKey: String
    private let legacyRefreshTokenKey: String
    private let legacyPaymentMethodKey: String
    private let readItem: ReadItem
    private let writeItem: WriteItem
    private let deleteItem: DeleteItem

    private var didLoad = false
    private var cached: StoredAccountCredentials?

    init(
        accountKey: String,
        legacyAccessTokenKey: String,
        legacyRefreshTokenKey: String,
        legacyPaymentMethodKey: String,
        readItem: @escaping ReadItem,
        writeItem: @escaping WriteItem,
        deleteItem: @escaping DeleteItem
    ) {
        self.accountKey = accountKey
        self.legacyAccessTokenKey = legacyAccessTokenKey
        self.legacyRefreshTokenKey = legacyRefreshTokenKey
        self.legacyPaymentMethodKey = legacyPaymentMethodKey
        self.readItem = readItem
        self.writeItem = writeItem
        self.deleteItem = deleteItem
    }

    /// Whether the Keychain has already been consulted in this process, so the next ``load()`` cannot prompt.
    var hasLoaded: Bool { didLoad }

    func load() -> StoredAccountCredentials? {
        if didLoad { return cached }
        didLoad = true
        if let json = readItem(accountKey),
           let data = json.data(using: .utf8),
           let credentials = try? JSONDecoder().decode(StoredAccountCredentials.self, from: data) {
            cached = credentials
            return credentials
        }
        cached = migrateLegacyItems()
        return cached
    }

    func save(accessToken: String, refreshToken: String, hasPaymentMethod: Bool) throws {
        let credentials = StoredAccountCredentials(
            accessToken: accessToken,
            refreshToken: refreshToken,
            hasPaymentMethod: hasPaymentMethod
        )
        try persist(credentials)
        deleteLegacyItems()
    }

    /// Records the payment flag with the stored tokens. Does nothing when nobody is signed in, because the flag is meaningless without an account.
    func updateHasPaymentMethod(_ hasPaymentMethod: Bool) {
        guard var credentials = load(), credentials.hasPaymentMethod != hasPaymentMethod else { return }
        credentials.hasPaymentMethod = hasPaymentMethod
        try? persist(credentials)
    }

    func clear() {
        deleteItem(accountKey)
        deleteLegacyItems()
        didLoad = true
        cached = nil
    }

    private func persist(_ credentials: StoredAccountCredentials) throws {
        let data = try JSONEncoder().encode(credentials)
        guard let json = String(data: data, encoding: .utf8) else { return }
        try writeItem(accountKey, json)
        didLoad = true
        cached = credentials
    }

    private func migrateLegacyItems() -> StoredAccountCredentials? {
        guard let accessToken = readItem(legacyAccessTokenKey),
              let refreshToken = readItem(legacyRefreshTokenKey) else {
            return nil
        }
        let credentials = StoredAccountCredentials(
            accessToken: accessToken,
            refreshToken: refreshToken,
            hasPaymentMethod: readItem(legacyPaymentMethodKey) == "true"
        )
        do {
            try persist(credentials)
            deleteLegacyItems()
        } catch {
            // Keep serving the credentials from memory; the old items stay so a later launch can retry the migration.
        }
        return credentials
    }

    private func deleteLegacyItems() {
        deleteItem(legacyAccessTokenKey)
        deleteItem(legacyRefreshTokenKey)
        deleteItem(legacyPaymentMethodKey)
    }
}
