import Foundation
import os

/// Client for communicating with the Basil Auth Service
final class AuthClient {
    // MARK: - Properties
    private let logger = Logger(subsystem: "com.basil.client", category: "AuthClient")
    
    private let baseURL = "https://basilauthservice-production.up.railway.app"
    
    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        
        // Custom date decoding strategy to handle multiple formats from backend
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            
            // Try ISO8601 first (standard format)
            let iso8601Formatter = ISO8601DateFormatter()
            iso8601Formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = iso8601Formatter.date(from: dateString) {
                return date
            }
            
            // Try without fractional seconds
            iso8601Formatter.formatOptions = [.withInternetDateTime]
            if let date = iso8601Formatter.date(from: dateString) {
                return date
            }
            
            // Try PostgreSQL TIMESTAMP format (e.g., "2025-12-15 13:22:02.425")
            let postgresFormatter = DateFormatter()
            postgresFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
            postgresFormatter.timeZone = TimeZone(secondsFromGMT: 0)
            if let date = postgresFormatter.date(from: dateString) {
                return date
            }
            
            // Try without milliseconds
            postgresFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
            if let date = postgresFormatter.date(from: dateString) {
                return date
            }
            
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date string: \(dateString)")
        }
        
        return decoder
    }()
    
    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()
    
    // MARK: - Authentication Endpoints
    
    func register(email: String, password: String) async throws -> AuthTokens {
        let request = RegisterRequest(email: email, password: password)
        let data = try await post("/auth/register/email", body: request)
        
        do {
            return try decoder.decode(AuthTokens.self, from: data)
        } catch {
            // Check for specific error responses
            if let errorResponse = try? JSONDecoder().decode(ErrorResponse.self, from: data) {
                if errorResponse.error.contains("already registered") {
                    throw AuthError.emailAlreadyRegistered
                }
                throw AuthError.networkError(errorResponse.error)
            }
            throw AuthError.networkError("Failed to decode response")
        }
    }
    
    func login(email: String, password: String) async throws -> AuthTokens {
        let request = LoginRequest(email: email, password: password)
        let data = try await post("/auth/login/email", body: request)
        
        do {
            return try decoder.decode(AuthTokens.self, from: data)
        } catch {
            if let errorResponse = try? JSONDecoder().decode(ErrorResponse.self, from: data) {
                if errorResponse.error.contains("Invalid") {
                    throw AuthError.invalidCredentials
                }
                throw AuthError.networkError(errorResponse.error)
            }
            throw AuthError.networkError("Failed to decode response")
        }
    }
    
    func startGoogleAuth() async throws -> GoogleAuthStartResponse {
        let data = try await get("/auth/google/start")
        return try decoder.decode(GoogleAuthStartResponse.self, from: data)
    }
    
    func completeGoogleAuth(code: String, redirectUri: String? = nil) async throws -> AuthTokens {
        let request = GoogleAuthCallbackRequest(code: code, redirectUri: redirectUri)
        let data = try await post("/auth/google/callback", body: request)
        return try decoder.decode(AuthTokens.self, from: data)
    }
    
    func refreshToken(refreshToken: String) async throws -> AuthTokens {
        let request = RefreshTokenRequest(refreshToken: refreshToken)
        let data = try await post("/auth/refresh", body: request)
        return try decoder.decode(AuthTokens.self, from: data)
    }
    
    func logout(accessToken: String) async throws {
        _ = try await post("/auth/logout", body: EmptyBody(), accessToken: accessToken)
    }
    
    func getCurrentUser(accessToken: String) async throws -> AuthUser {
        let data = try await get("/auth/me", accessToken: accessToken)
        return try decoder.decode(AuthUser.self, from: data)
    }
    
    // MARK: - Billing Endpoints
    
    func getBillingStatus(accessToken: String) async throws -> BillingStatusResponse {
        let data = try await get("/billing/status", accessToken: accessToken)
        return try decoder.decode(BillingStatusResponse.self, from: data)
    }
    
    func setupPaymentMethod(accessToken: String) async throws -> PaymentSetupResponse {
        let data = try await post("/billing/setup", body: EmptyBody(), accessToken: accessToken)
        return try decoder.decode(PaymentSetupResponse.self, from: data)
    }
    
    func getPaymentMethod(accessToken: String) async throws -> PaymentMethodResponse {
        let data = try await get("/billing/payment-method", accessToken: accessToken)
        return try decoder.decode(PaymentMethodResponse.self, from: data)
    }

    // MARK: - Account Endpoints

    /// Permanently deletes the authenticated user's account.
    /// `BasilAuthService` runs final billing before deleting; a `400`
    /// response means deletion was blocked (e.g. outstanding balance)
    /// and carries `{error, message}` where `message` is the
    /// user-facing reason — surfaced verbatim via `.accountDeletionBlocked`.
    func deleteAccount(accessToken: String) async throws -> DeleteAccountResponse {
        guard let url = URL(string: baseURL + "/account") else {
            throw AuthError.networkError("Invalid URL")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 60
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.networkError("Invalid response")
        }

        if httpResponse.statusCode == 401 {
            throw AuthError.tokenExpired
        }

        if httpResponse.statusCode >= 400 {
            if let blocked = try? JSONDecoder().decode(DeleteAccountBlockedResponse.self, from: data) {
                throw AuthError.accountDeletionBlocked(blocked.message)
            }
            throw AuthError.serverError(httpResponse.statusCode)
        }

        return try decoder.decode(DeleteAccountResponse.self, from: data)
    }
    
    // MARK: - Usage Endpoints
    
    func getCurrentUsage(accessToken: String) async throws -> UsageResponse {
        let data = try await get("/usage/current", accessToken: accessToken)
        return try decoder.decode(UsageResponse.self, from: data)
    }
    
    // MARK: - OpenRouter Proxy
    
    func proxyRequest(_ request: ProxyRequest, accessToken: String) async throws -> Data {
        return try await post("/route/request", body: request, accessToken: accessToken)
    }
    
    // MARK: - Private Helpers
    
    private func get(_ endpoint: String, accessToken: String? = nil) async throws -> Data {
        guard let url = URL(string: baseURL + endpoint) else {
            throw AuthError.networkError("Invalid URL")
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        
        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.networkError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 {
            throw AuthError.tokenExpired
        }
        
        if httpResponse.statusCode == 402 {
            throw AuthError.paymentRequired
        }
        
        if httpResponse.statusCode == 403 {
            throw AuthError.subscriptionInactive
        }
        
        if httpResponse.statusCode >= 400 {
            throw AuthError.serverError(httpResponse.statusCode)
        }
        
        return data
    }
    
    private func post<T: Encodable>(_ endpoint: String, body: T, accessToken: String? = nil) async throws -> Data {
        guard let url = URL(string: baseURL + endpoint) else {
            throw AuthError.networkError("Invalid URL")
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        request.httpBody = try encoder.encode(body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.networkError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 {
            throw AuthError.tokenExpired
        }
        
        if httpResponse.statusCode == 402 {
            throw AuthError.paymentRequired
        }
        
        if httpResponse.statusCode == 403 {
            throw AuthError.subscriptionInactive
        }
        
        if httpResponse.statusCode >= 400 {
            // Try to extract error message
            if let errorResponse = try? JSONDecoder().decode(ErrorResponse.self, from: data) {
                throw AuthError.networkError(errorResponse.error)
            }
            throw AuthError.serverError(httpResponse.statusCode)
        }
        
        return data
    }
}

// MARK: - Helper Types

private struct ErrorResponse: Codable {
    let error: String
}

/// Decodes the `{error, message}` shape `BasilAuthService` returns for
/// both the `400` billing-blocked case and its `500` catch-all
/// (`BasilAuthService/src/routes/auth.ts` lines 461-464 and 488-493).
private struct DeleteAccountBlockedResponse: Codable {
    let error: String
    let message: String
}

