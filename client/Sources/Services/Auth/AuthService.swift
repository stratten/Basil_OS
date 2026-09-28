import Foundation
import Security
import os

/// Service for managing user authentication state
@MainActor
final class AuthService: ObservableObject {
    // MARK: - Singleton
    static let shared = AuthService()
    
    // MARK: - Published State
    @Published private(set) var state: AuthState = .unauthenticated
    @Published private(set) var currentUser: AuthUser?
    @Published private(set) var hasPaymentMethod: Bool = false
    
    /// API key preference - delegates to APIKeyPreferenceManager for decoupled management.
    /// This property is kept for backwards compatibility but preference management
    /// is now handled by APIKeyPreferenceManager.
    var apiKeyPreference: APIKeyPreference {
        APIKeyPreferenceManager.shared.preference
    }
    
    // MARK: - Properties
    private let logger = Logger(subsystem: "com.basil.client", category: "AuthService")
    private let authClient = AuthClient()
    private let apiClient = APIClient.shared
    
    // Flag to prevent clearing auth state during OAuth flow
    private var oauthFlowInProgress = false
    
    // Cached tokens to avoid repeated keychain access
    private var cachedAccessToken: String?
    private var cachedRefreshToken: String?

    // In-memory mirror of the per-connection MCP token Keychain slots.
    //
    // Why this exists: every backend ``mcp_token_request`` for a remote
    // MCP tool dispatch causes a Keychain read, and on dev rebuilds the
    // app's code-signing identity changes, so each read pops a system
    // prompt. With this cache the first request after launch hits the
    // Keychain once (one prompt at most), and every subsequent request
    // for the same connection during the session is satisfied from
    // memory. ``storeMCPToken`` writes through, ``deleteMCPToken``
    // clears, and rotation re-issued from the backend overwrites both
    // layers via ``storeMCPToken``, so the cache cannot drift.
    //
    // Keyed by ``connectionId``, mirroring the Keychain key namespace.
    // ``@MainActor`` isolation on the enclosing class is the
    // synchronization model — these mutate from
    // ``WebSocketService_MCP`` handlers which are themselves MainActor.
    var cachedMCPAccessTokens: [String: String] = [:]
    var cachedMCPRefreshTokens: [String: String] = [:]
    
    // Keychain keys - tokens and payment status stored securely
    private var accessTokenKey: String { BasilRuntimeProfile.credentialKey("com.basil.accessToken") }
    private var refreshTokenKey: String { BasilRuntimeProfile.credentialKey("com.basil.refreshToken") }
    private var hasPaymentMethodKey: String { BasilRuntimeProfile.credentialKey("com.basil.hasPaymentMethod") }
    
    var isAuthenticated: Bool {
        if case .authenticated = state { return true }
        return false
    }
    
    var canUseAppKeys: Bool {
        isAuthenticated && hasPaymentMethod && apiKeyPreference.isBasilCloudAlias
    }
    
    // MARK: - Initialization
    private init() {
        // Try to restore session on init
        Task {
            await restoreSession()
        }
    }
    
    // MARK: - Public Methods
    
    /// Register with email and password
    func register(email: String, password: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.register(email: email, password: password)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User registered: \(email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Login with email and password
    func login(email: String, password: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.login(email: email, password: password)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User logged in: \(email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Get Google OAuth URL
    func getGoogleAuthURL() async throws -> URL {
        // Mark OAuth flow as in progress to prevent token clearing
        oauthFlowInProgress = true
        logger.info("🔐 OAuth flow started")
        
        // Safety timeout: Clear OAuth flag after 5 minutes in case flow never completes
        Task {
            try? await Task.sleep(nanoseconds: 5 * 60 * 1_000_000_000) // 5 minutes
            if oauthFlowInProgress {
                logger.warning("🔐 OAuth flow timed out - clearing flag")
                oauthFlowInProgress = false
            }
        }
        
        let response = try await authClient.startGoogleAuth()
        guard let url = URL(string: response.authorizationUrl) else {
            oauthFlowInProgress = false
            throw AuthError.networkError("Invalid authorization URL")
        }
        return url
    }
    
    /// Complete Google OAuth with authorization code
    func completeGoogleAuth(code: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.completeGoogleAuth(code: code)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User logged in via Google: \(user.email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Complete OAuth with tokens received from URL callback
    func completeOAuthWithTokens(_ tokens: AuthTokens) async throws {
        NSLog("🚨🚨🚨 [AuthService] completeOAuthWithTokens CALLED")
        state = .loading
        logger.info("🔐 Completing OAuth with tokens from URL callback")
        
        do {
            NSLog("🚨🚨🚨 [AuthService] About to save tokens to keychain")
            try saveTokens(tokens)
            NSLog("🚨🚨🚨 [AuthService] Tokens saved to keychain successfully")
            logger.info("🔐 Tokens saved to keychain")
            
            NSLog("🚨🚨🚨 [AuthService] Fetching user with access token")
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            NSLog("🚨🚨🚨 [AuthService] User fetched: %@", user.email)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Clear OAuth flow flag before syncing
            oauthFlowInProgress = false
            NSLog("🚨🚨🚨 [AuthService] OAuth flow flag cleared")
            logger.info("🔐 OAuth flow marked as complete")
            
            // Sync with backend
            NSLog("🚨🚨🚨 [AuthService] Syncing to backend")
            await syncAuthSettingsToBackend()
            NSLog("🚨🚨🚨 [AuthService] Backend sync complete")
            
            logger.info("OAuth completed via URL callback for: \(user.email)")
            NSLog("🚨🚨🚨 [AuthService] completeOAuthWithTokens COMPLETED SUCCESSFULLY")
        } catch {
            NSLog("🚨🚨🚨 [AuthService] ERROR in completeOAuthWithTokens: %@", error.localizedDescription)
            // Clear OAuth flow flag on error too
            oauthFlowInProgress = false
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Logout
    func logout() async {
        if let token = getAccessToken() {
            try? await authClient.logout(accessToken: token)
        }
        
        clearTokens()
        currentUser = nil
        hasPaymentMethod = false
        state = .unauthenticated
        
        // Sync with backend
        await syncAuthSettingsToBackend()
        
        logger.info("User logged out")
    }

    /// Permanently deletes the authenticated user's account via
    /// `BasilAuthService` (which runs final billing first). Unlike
    /// `logout()`, this only clears local session state on a confirmed
    /// server-side success -- a thrown `AuthError.accountDeletionBlocked`
    /// (or any other error) leaves the session untouched so the caller's
    /// UI can surface the exact reason and let the user retry or resolve
    /// the block (e.g. pay an outstanding balance) without being logged out.
    func deleteAccount() async throws {
        guard let token = getAccessToken() else {
            throw AuthError.notAuthenticated
        }

        _ = try await authClient.deleteAccount(accessToken: token)

        clearTokens()
        currentUser = nil
        hasPaymentMethod = false
        state = .unauthenticated

        await syncAuthSettingsToBackend()

        logger.info("User account deleted")
    }
    
    /// Refresh user data
    func refreshUserData() async throws {
        guard let token = getAccessToken() else {
            throw AuthError.notAuthenticated
        }
        
        let user = try await authClient.getCurrentUser(accessToken: token)
        currentUser = user
        hasPaymentMethod = user.hasPaymentMethod
        saveHasPaymentMethod(user.hasPaymentMethod)
        
        if case .authenticated(_, let tokens) = state {
            state = .authenticated(user: user, tokens: tokens)
        }
        
        // Sync with backend
        await syncAuthSettingsToBackend()
    }
    
    /// Set API key preference - delegates to APIKeyPreferenceManager.
    /// This method is kept for backwards compatibility. New code should use
    /// APIKeyPreferenceManager.shared.setPreference() directly.
    func setAPIKeyPreference(_ preference: APIKeyPreference) {
        // Delegate to the preference manager which handles backend sync.
        APIKeyPreferenceManager.shared.setPreference(preference)
    }
    
    /// Get current access token (cached to avoid repeated keychain prompts)
    func getAccessToken() -> String? {
        // Return cached token if available
        if let cached = cachedAccessToken {
            return cached
        }
        
        // Otherwise read from keychain and cache it
        if let token = getFromKeychain(key: accessTokenKey) {
            cachedAccessToken = token
            return token
        }
        
        return nil
    }
    
    // MARK: - Backend Settings Sync
    
    /// Sync auth settings to backend (api_key_preference, is_authenticated, user_email)
    private func syncAuthSettingsToBackend() async {
        NSLog("🚨🚨🚨 [AuthService] syncAuthSettingsToBackend called, oauthFlowInProgress: %@", oauthFlowInProgress ? "YES" : "NO")
        // Skip syncing if OAuth flow is in progress to prevent clearing tokens
        if oauthFlowInProgress {
            NSLog("🚨🚨🚨 [AuthService] SKIPPING backend sync - OAuth flow in progress")
            logger.info("🔐 Skipping backend sync - OAuth flow in progress")
            return
        }
        
        NSLog("🚨🚨🚨 [AuthService] Syncing auth settings: authenticated=%@, email=%@", isAuthenticated ? "YES" : "NO", currentUser?.email ?? "nil")
        do {
            let settings = AuthSettingsUpdate(
                apiKeyPreference: apiKeyPreference.rawValue,
                isAuthenticated: isAuthenticated,
                userEmail: currentUser?.email
            )
            try await apiClient.updateAuthSettings(settings)
            
            // Also sync access token to Python backend for auth proxy routing
            if isAuthenticated, let token = getAccessToken() {
                try await apiClient.setAuthToken(token)
                logger.debug("Access token synced to Python backend")
            } else {
                try await apiClient.clearAuthToken()
                logger.debug("Access token cleared from Python backend")
            }
            
            logger.debug("Auth settings synced to backend")
        } catch {
            logger.warning("Failed to sync auth settings to backend: \(error.localizedDescription)")
        }
    }
    
    /// Load auth settings from backend - delegates to APIKeyPreferenceManager
    private func loadAuthSettingsFromBackend() async {
        // API key preference is now managed by APIKeyPreferenceManager
        // which loads from backend on its own init. We just ensure it's loaded.
        await APIKeyPreferenceManager.shared.loadPreference()
        logger.debug("Auth settings loaded via APIKeyPreferenceManager")
    }
    
    // MARK: - Private Methods
    
    private func restoreSession() async {
        // First, load API key preference from backend settings
        await loadAuthSettingsFromBackend()
        
        // Check for stored tokens
        guard let accessToken = getFromKeychain(key: accessTokenKey),
              let refreshToken = getFromKeychain(key: refreshTokenKey) else {
            state = .unauthenticated
            // Restore cached hasPaymentMethod from Keychain
            hasPaymentMethod = getFromKeychain(key: hasPaymentMethodKey) == "true"
            return
        }
        
        // Cache tokens to avoid repeated keychain access
        cachedAccessToken = accessToken
        cachedRefreshToken = refreshToken
        
        state = .loading
        
        // Try to get user with existing token
        do {
            let user = try await authClient.getCurrentUser(accessToken: accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            
            let tokens = AuthTokens(
                accessToken: accessToken,
                refreshToken: refreshToken,
                tokenType: "bearer",
                expiresIn: 900 // Assume 15 min, will refresh if needed
            )
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync auth state to backend
            await syncAuthSettingsToBackend()
            
            logger.info("Session restored for: \(user.email)")
        } catch {
            // Token might be expired, try to refresh
            do {
                let newTokens = try await authClient.refreshToken(refreshToken: refreshToken)
                try saveTokens(newTokens)
                
                let user = try await authClient.getCurrentUser(accessToken: newTokens.accessToken)
                currentUser = user
                hasPaymentMethod = user.hasPaymentMethod
                saveHasPaymentMethod(user.hasPaymentMethod)
                state = .authenticated(user: user, tokens: newTokens)
                
                // Sync auth state to backend
                await syncAuthSettingsToBackend()
                
                logger.info("Session refreshed for: \(user.email)")
            } catch {
                // Failed to refresh, clear and go to unauthenticated
                clearTokens()
                state = .unauthenticated
                await syncAuthSettingsToBackend()
                logger.warning("Failed to restore session: \(error.localizedDescription)")
            }
        }
    }
    
    private func saveTokens(_ tokens: AuthTokens) throws {
        try saveToKeychain(key: accessTokenKey, value: tokens.accessToken)
        try saveToKeychain(key: refreshTokenKey, value: tokens.refreshToken)
        
        // Cache tokens to avoid repeated keychain access
        cachedAccessToken = tokens.accessToken
        cachedRefreshToken = tokens.refreshToken
    }
    
    private func saveHasPaymentMethod(_ value: Bool) {
        try? saveToKeychain(key: hasPaymentMethodKey, value: value ? "true" : "false")
    }
    
    private func clearTokens() {
        deleteFromKeychain(key: accessTokenKey)
        deleteFromKeychain(key: refreshTokenKey)
        deleteFromKeychain(key: hasPaymentMethodKey)
        
        // Clear cached tokens
        cachedAccessToken = nil
        cachedRefreshToken = nil
    }
    
    // MARK: - Keychain Helpers
    
    func saveToKeychain(key: String, value: String) throws {
        let data = value.data(using: .utf8)!

        // Stored items carry a ``kSecAttrAccessControl`` ACL with the
        // ``.userPresence`` flag. On read, macOS presents the system
        // sheet that accepts EITHER an enrolled biometric (Touch ID)
        // OR the user's Mac login password — the user picks the method
        // they prefer per prompt. This replaces the previous
        // ``kSecAttrAccessibleWhenUnlockedThisDeviceOnly`` accessibility,
        // which produced a password-only sheet whenever the system
        // needed to re-authorize an item (most commonly during dev
        // rebuilds when the app's code-signing identity changed).
        //
        // ``kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly`` is the
        // accessibility class the ACL flags require: a biometric ACL
        // is meaningless without a passcode, so this constraint must
        // accompany ``.userPresence``. Every macOS user account has a
        // login password by definition, so this never fails in
        // practice on a logged-in machine.
        var aclError: Unmanaged<CFError>?
        guard let accessControl = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
            [.userPresence],
            &aclError
        ) else {
            let underlying = aclError?.takeRetainedValue()
            let message = (underlying as Error?)?.localizedDescription ?? "unknown"
            logger.error("Failed to create Keychain access control: \(message)")
            DevLogger.shared.error(
                "Keychain ACL creation failed: \(message)",
                context: "AuthService.saveToKeychain"
            )
            throw AuthError.networkError("Failed to create keychain access control: \(message)")
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessControl as String: accessControl
        ]

        // Delete any existing item first. This both prevents
        // ``errSecDuplicateItem`` and gives us automatic in-place
        // migration: an entry written with the previous accessibility
        // attribute is removed here and rewritten below with the new
        // ACL on the very next save.
        let deleteQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(deleteQuery as CFDictionary)

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            logger.error("Failed to save to keychain: \(status)")
            DevLogger.shared.error(
                "Keychain SecItemAdd failed (status=\(status)) for key=\(key)",
                context: "AuthService.saveToKeychain"
            )

            if status == errSecMissingEntitlement {
                // Ad-hoc/dev signing may not carry the entitlement needed for
                // kSecAttrAccessControl. Fall back to the pre-ACL storage mode
                // so reconnects keep working in dev; properly signed builds
                // still get the biometric/passcode ACL above.
                let fallbackQuery: [String: Any] = [
                    kSecClass as String: kSecClassGenericPassword,
                    kSecAttrAccount as String: key,
                    kSecValueData as String: data,
                    kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
                ]
                let fallbackStatus = SecItemAdd(fallbackQuery as CFDictionary, nil)
                if fallbackStatus == errSecSuccess {
                    DevLogger.shared.info(
                        "Keychain saved with dev fallback accessibility for key=\(key)",
                        context: "AuthService.saveToKeychain"
                    )
                    return
                }
                logger.error("Failed to save fallback keychain item: \(fallbackStatus)")
                DevLogger.shared.error(
                    "Keychain fallback SecItemAdd failed (status=\(fallbackStatus)) for key=\(key)",
                    context: "AuthService.saveToKeychain"
                )
            }
            throw AuthError.networkError("Failed to save to keychain")
        }
    }
    
    func getFromKeychain(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        
        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8) else {
            if status != errSecItemNotFound {
                logger.error("Keychain read failed: \(status)")
            }
            return nil
        }
        
        return value
    }
    
    func deleteFromKeychain(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
    }

}

