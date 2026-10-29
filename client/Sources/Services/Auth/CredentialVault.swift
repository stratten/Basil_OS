import Foundation

/// The one Keychain item that holds every secret Basil's client stores: the account session, each MCP connection's tokens, and the provider API keys the user supplied.
///
/// Keeping everything in a single item means macOS asks for permission to read it at most once per launch of a build whose code signature changed, instead of once per secret. A Developer ID build keeps a stable code-signing requirement, so it is never asked after the item is first created.
///
/// The vault is read once per process and then held in memory. ``update(_:)`` rewrites the whole item and the cache together, so the cache cannot drift from the Keychain. If the vault exists but cannot be read or decoded (for example the user chose Deny), ``load()`` returns nil without remembering that state, and ``update(_:)`` refuses to write, so a denied prompt can never erase the other secrets.
@MainActor
final class CredentialVault {
    typealias ReadItem = (_ key: String) -> String?
    typealias WriteItem = (_ key: String, _ value: String) throws -> Void
    /// Whether an item exists, answered from its attributes alone so it never needs permission to read the secret.
    typealias ItemExists = (_ key: String) -> Bool

    /// One MCP connection's tokens. Kept identical to the layout version 1 of the vault used.
    struct ConnectionEntry: Codable, Equatable {
        var access: String?
        var refresh: String?
    }

    struct Contents: Codable, Equatable {
        var version: Int = CredentialVaultFormat.currentVersion
        var account: StoredAccountCredentials?
        var connections: [String: ConnectionEntry] = [:]
        var providerKeys: [String: String] = [:]

        private enum CodingKeys: String, CodingKey {
            case version
            case account
            case connections
            case providerKeys
        }

        init() {}

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            version = try container.decodeIfPresent(Int.self, forKey: .version) ?? 1
            account = try container.decodeIfPresent(StoredAccountCredentials.self, forKey: .account)
            connections = try container.decodeIfPresent([String: ConnectionEntry].self, forKey: .connections) ?? [:]
            providerKeys = try container.decodeIfPresent([String: String].self, forKey: .providerKeys) ?? [:]
        }
    }

    static let shared = CredentialVault(
        vaultKey: BasilRuntimeProfile.credentialKey("com.basil.mcpTokenVault"),
        readItem: LoginKeychainItems.read,
        writeItem: LoginKeychainItems.write,
        itemExists: LoginKeychainItems.exists
    )

    private let vaultKey: String
    private let readItem: ReadItem
    private let writeItem: WriteItem
    private let itemExists: ItemExists

    /// The vault as last read or written in this process; nil until it has been read successfully.
    private var cached: Contents?

    init(
        vaultKey: String,
        readItem: @escaping ReadItem,
        writeItem: @escaping WriteItem,
        itemExists: @escaping ItemExists = { _ in false }
    ) {
        self.vaultKey = vaultKey
        self.readItem = readItem
        self.writeItem = writeItem
        self.itemExists = itemExists
    }

    /// The vault as last read or written in this process, without touching the Keychain. Nil until ``load()`` has succeeded once.
    var cachedContents: Contents? { cached }

    /// Loads the vault once per process. Returns nil only when a vault exists but could not be read or decoded; that state is not remembered, so the next request tries again, and it is never treated as an empty vault.
    func load() -> Contents? {
        if let cached { return cached }
        if let raw = readItem(vaultKey) {
            guard let data = raw.data(using: .utf8), let decoded = try? JSONDecoder().decode(Contents.self, from: data) else {
                return nil
            }
            cached = decoded
            return decoded
        }
        if itemExists(vaultKey) { return nil }
        let empty = Contents()
        cached = empty
        return empty
    }

    /// Applies a change and writes the whole vault. Throws ``CredentialVaultError/unreadable`` without writing anything when the vault cannot be read, and rethrows a failed write without changing the cache.
    func update(_ change: (inout Contents) -> Void) throws {
        guard var current = load() else { throw CredentialVaultError.unreadable }
        change(&current)
        current.version = CredentialVaultFormat.currentVersion
        let data = try JSONEncoder().encode(current)
        guard let text = String(data: data, encoding: .utf8) else { return }
        try writeItem(vaultKey, text)
        cached = current
    }

    /// Applies a change to the in-memory copy only. Used when moving earlier items into the vault failed to save, so the tokens stay usable for this process while the earlier items remain in the Keychain.
    func remember(_ change: (inout Contents) -> Void) {
        guard var current = load() else { return }
        change(&current)
        cached = current
    }
}

/// The vault's on-disk layout version. A plain non-isolated enum so the nested `Contents` default value can read it from any context.
enum CredentialVaultFormat {
    static let currentVersion = 2
}

enum CredentialVaultError: LocalizedError {
    case unreadable

    var errorDescription: String? {
        switch self {
        case .unreadable:
            return "Basil could not open its Keychain vault. Quit and reopen Basil, and choose Always Allow when macOS asks to use the Keychain."
        }
    }
}
