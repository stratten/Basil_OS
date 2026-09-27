import Foundation

// MARK: - Authentication Models

/// User authentication state
enum AuthState {
    case unauthenticated
    case authenticated(user: AuthUser, tokens: AuthTokens)
    case loading
}

/// Authenticated user info
struct AuthUser: Codable {
    let id: String
    let email: String
    let createdAt: Date
    let subscriptionStatus: String
    let hasPaymentMethod: Bool
    
    enum CodingKeys: String, CodingKey {
        case id, email
        case createdAt = "created_at"
        case subscriptionStatus = "subscription_status"
        case hasPaymentMethod = "has_payment_method"
    }
}

/// Authentication tokens
struct AuthTokens: Codable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresIn: Int
    
    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
    }
}

/// API key preference for model access
enum APIKeyPreference: String, Codable {
    case useBasilCloud = "basil_cloud" // Route through Basil Cloud: included credit first, account-backed after
    case useAppKeys = "app_keys"       // Legacy alias for Basil Cloud account-backed routing
    case useTrial = "trial"            // Legacy alias for Basil Cloud included-credit routing
    case useOwnKeys = "own_keys"       // Direct to providers, no billing
    case useLocalModels = "local"      // Local models only
    
    var isBasilCloudAlias: Bool {
        self == .useBasilCloud || self == .useAppKeys || self == .useTrial
    }
}

// MARK: - Request Models

struct RegisterRequest: Codable {
    let email: String
    let password: String
}

struct LoginRequest: Codable {
    let email: String
    let password: String
}

struct GoogleAuthCallbackRequest: Codable {
    let code: String
    let redirectUri: String?
    
    enum CodingKeys: String, CodingKey {
        case code
        case redirectUri = "redirect_uri"
    }
}

struct RefreshTokenRequest: Codable {
    let refreshToken: String
    
    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

// MARK: - Response Models

struct GoogleAuthStartResponse: Codable {
    let authorizationUrl: String
    
    enum CodingKeys: String, CodingKey {
        case authorizationUrl = "authorization_url"
    }
}

struct BillingStatusResponse: Codable {
    let subscriptionStatus: String
    let hasPaymentMethod: Bool
    let stripeCustomerId: String?
    let currentPeriodUsageUsd: Double
    
    enum CodingKeys: String, CodingKey {
        case subscriptionStatus = "subscription_status"
        case hasPaymentMethod = "has_payment_method"
        case stripeCustomerId = "stripe_customer_id"
        case currentPeriodUsageUsd = "current_period_usage_usd"
    }
}

struct PaymentSetupResponse: Codable {
    let clientSecret: String
    let setupIntentId: String
    
    enum CodingKeys: String, CodingKey {
        case clientSecret = "client_secret"
        case setupIntentId = "setup_intent_id"
    }
}

struct PaymentMethodResponse: Codable {
    let hasPaymentMethod: Bool
    let cardBrand: String?
    let cardLast4: String?
    let cardExpMonth: Int?
    let cardExpYear: Int?
    
    enum CodingKeys: String, CodingKey {
        case hasPaymentMethod = "has_payment_method"
        case cardBrand = "card_brand"
        case cardLast4 = "card_last4"
        case cardExpMonth = "card_exp_month"
        case cardExpYear = "card_exp_year"
    }
}

/// Response from `DELETE /account` on success. Mirrors
/// `BasilAuthService/src/routes/auth.ts` lines 472-483: `finalInvoice`
/// is present only when a final billing charge was made before deletion.
struct DeleteAccountResponse: Codable {
    let success: Bool
    let message: String
    let finalInvoice: FinalInvoice?

    struct FinalInvoice: Codable {
        let invoiceId: String
        let amountCharged: Double

        enum CodingKeys: String, CodingKey {
            case invoiceId = "invoice_id"
            case amountCharged = "amount_charged"
        }
    }

    enum CodingKeys: String, CodingKey {
        case success, message
        case finalInvoice = "final_invoice"
    }
}

struct UsageResponse: Codable {
    let periodStart: Date
    let periodEnd: Date
    let totalCostUsd: Double
    let totalInputTokens: Int
    let totalOutputTokens: Int
    let eventsCount: Int
    let usageByModel: [String: ModelUsage]
    
    enum CodingKeys: String, CodingKey {
        case periodStart = "period_start"
        case periodEnd = "period_end"
        case totalCostUsd = "total_cost_usd"
        case totalInputTokens = "total_input_tokens"
        case totalOutputTokens = "total_output_tokens"
        case eventsCount = "events_count"
        case usageByModel = "usage_by_model"
    }
}

struct ModelUsage: Codable {
    let inputTokens: Int
    let outputTokens: Int
    let costUsd: Double
    
    enum CodingKeys: String, CodingKey {
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case costUsd = "cost_usd"
    }
}

// MARK: - OpenRouter Proxy Models

struct ProxyRequest: Codable {
    let provider: String
    let model: String
    let messages: [ProxyMessage]
    let temperature: Double?
    let maxTokens: Int?
    let stream: Bool?
    
    enum CodingKeys: String, CodingKey {
        case provider, model, messages, temperature, stream
        case maxTokens = "max_tokens"
    }
}

struct ProxyMessage: Codable {
    let role: String
    let content: String
}

// MARK: - Errors

enum AuthError: Error {
    case invalidCredentials
    case emailAlreadyRegistered
    case networkError(String)
    case serverError(Int)
    case tokenExpired
    case notAuthenticated
    case paymentRequired
    case subscriptionInactive
    case accountDeletionBlocked(String)
}

extension AuthError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case .invalidCredentials:
            return "Invalid email or password"
        case .emailAlreadyRegistered:
            return "This email is already registered"
        case .networkError(let message):
            return "Network error: \(message)"
        case .serverError(let code):
            return "Server error (code: \(code))"
        case .tokenExpired:
            return "Session expired. Please log in again."
        case .notAuthenticated:
            return "Not authenticated"
        case .paymentRequired:
            return "Payment method required"
        case .subscriptionInactive:
            return "Subscription is not active"
        case .accountDeletionBlocked(let message):
            return message
        }
    }
}

// MARK: - Backend Settings Sync Models

/// Request to update auth settings in backend preferences.
/// Only apiKeyPreference is required. If isAuthenticated or userEmail are nil,
/// the backend preserves existing values. This allows preference-only updates
/// without requiring AuthService access (which would trigger keychain prompts).
struct AuthSettingsUpdate: Codable {
    let apiKeyPreference: String
    let isAuthenticated: Bool?
    let userEmail: String?
    
    /// Convenience initializer for preference-only updates (no auth state change)
    init(apiKeyPreference: String) {
        self.apiKeyPreference = apiKeyPreference
        self.isAuthenticated = nil
        self.userEmail = nil
    }
    
    /// Full initializer for auth state updates
    init(apiKeyPreference: String, isAuthenticated: Bool?, userEmail: String?) {
        self.apiKeyPreference = apiKeyPreference
        self.isAuthenticated = isAuthenticated
        self.userEmail = userEmail
    }
    
    enum CodingKeys: String, CodingKey {
        case apiKeyPreference = "api_key_preference"
        case isAuthenticated = "is_authenticated"
        case userEmail = "user_email"
    }
}

/// Response from backend auth settings
struct AuthSettingsResponse: Codable {
    let apiKeyPreference: String
    let isAuthenticated: Bool
    let userEmail: String?
    
    enum CodingKeys: String, CodingKey {
        case apiKeyPreference = "api_key_preference"
        case isAuthenticated = "is_authenticated"
        case userEmail = "user_email"
    }
}

