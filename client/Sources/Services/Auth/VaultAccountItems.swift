import Foundation

/// Presents the vault's `account` field as the single Keychain item ``AccountCredentialStore`` expects, so the account session lives in the same vault as every other secret.
///
/// Reads of the account key are answered from the vault. If the vault has no account but an earlier standalone account item exists, that item is copied into the vault and removed, so an existing sign-in survives the move. If the vault cannot be saved, the standalone item is kept. If the vault cannot be read at all, the standalone item (when present) still answers, so a denied vault prompt does not sign the user out. Every other key passes straight through to the plain Keychain closures.
@MainActor
final class VaultAccountItems {
    typealias ReadItem = (_ key: String) -> String?
    typealias WriteItem = (_ key: String, _ value: String) throws -> Void
    typealias DeleteItem = (_ key: String) -> Void

    private let vault: CredentialVault
    private let accountKey: String
    private let readItem: ReadItem
    private let writeItem: WriteItem
    private let deleteItem: DeleteItem

    init(
        vault: CredentialVault,
        accountKey: String,
        readItem: @escaping ReadItem,
        writeItem: @escaping WriteItem,
        deleteItem: @escaping DeleteItem
    ) {
        self.vault = vault
        self.accountKey = accountKey
        self.readItem = readItem
        self.writeItem = writeItem
        self.deleteItem = deleteItem
    }

    func read(key: String) -> String? {
        guard key == accountKey else { return readItem(key) }
        if let account = vault.load()?.account {
            return Self.encode(account)
        }
        guard let raw = readItem(accountKey) else { return nil }
        if let account = Self.decode(raw), (try? vault.update({ $0.account = account })) != nil {
            deleteItem(accountKey)
        }
        return raw
    }

    func write(key: String, value: String) throws {
        guard key == accountKey else {
            try writeItem(key, value)
            return
        }
        guard let account = Self.decode(value) else { return }
        try vault.update { $0.account = account }
        deleteItem(accountKey)
    }

    func delete(key: String) {
        guard key == accountKey else {
            deleteItem(key)
            return
        }
        do {
            try vault.update { $0.account = nil }
        } catch {
            LoginKeychainItems.logWarning("Could not remove the signed-out account from the vault")
        }
        deleteItem(accountKey)
    }

    private static func encode(_ account: StoredAccountCredentials) -> String? {
        guard let data = try? JSONEncoder().encode(account) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func decode(_ raw: String) -> StoredAccountCredentials? {
        guard let data = raw.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(StoredAccountCredentials.self, from: data)
    }
}
