import AppKit
import Foundation

/// Checks the sign-in and sign-up fields the Setup Assistant sends, with the same rules Settings → Account applies before it contacts the auth service.
enum SetupAccountCredentialValidation {
    static let minimumPasswordLength = 8

    static func loginError(email: String, password: String) -> String? {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty, trimmedEmail.contains("@") else {
            return "Enter the email address for your Basil account."
        }
        guard !password.isEmpty else {
            return "Enter your password."
        }
        return nil
    }

    static func signupError(email: String, password: String, confirmPassword: String) -> String? {
        if let error = loginError(email: email, password: password) {
            return error
        }
        guard password.count >= minimumPasswordLength else {
            return "Password must be at least \(minimumPasswordLength) characters."
        }
        guard password == confirmPassword else {
            return "Passwords don’t match."
        }
        return nil
    }
}

/// The page that collects a payment method through Stripe; it is the same page Settings → Account opens.
enum SetupAccountLinks {
    static let paymentSetupURLString = "https://basilauthservice-production.up.railway.app/web/payment"
}

/// Native half of the Basil Cloud sign-in, sign-up, and payment prompts in the Setup Assistant's model-access step, so a new user never has to leave setup for Settings → Account.
extension SetupAssistantWebView.Coordinator {
    func handleAccountLogin(payload: [String: Any]?, requestId: String?) {
        let email = (payload?["email"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let password = payload?["password"] as? String ?? ""
        if let error = SetupAccountCredentialValidation.loginError(email: email, password: password) {
            dispatchActionResult(requestId: requestId, status: "failed", message: error)
            return
        }
        Task { @MainActor in
            do {
                try await AuthService.shared.login(email: email, password: password)
                dispatchActionResult(requestId: requestId, status: "executed", message: "Signed in.", resultPayload: accountStatePayload())
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: error.localizedDescription)
            }
        }
    }

    func handleAccountSignup(payload: [String: Any]?, requestId: String?) {
        let email = (payload?["email"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let password = payload?["password"] as? String ?? ""
        let confirmPassword = payload?["confirmPassword"] as? String ?? ""
        if let error = SetupAccountCredentialValidation.signupError(
            email: email,
            password: password,
            confirmPassword: confirmPassword
        ) {
            dispatchActionResult(requestId: requestId, status: "failed", message: error)
            return
        }
        Task { @MainActor in
            do {
                try await AuthService.shared.register(email: email, password: password)
                dispatchActionResult(requestId: requestId, status: "executed", message: "Account created.", resultPayload: accountStatePayload())
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: error.localizedDescription)
            }
        }
    }

    func handleAccountGoogleSignIn(requestId: String?) {
        Task { @MainActor in
            do {
                let url = try await AuthService.shared.getGoogleAuthURL()
                NSWorkspace.shared.open(url)
                // The browser returns through `basil://auth/callback`, which the app delegate completes; this result only confirms the browser opened.
                dispatchActionResult(
                    requestId: requestId,
                    status: "executed",
                    message: "Finish signing in with Google in your browser, then come back here."
                )
            } catch {
                DevLogger.shared.error("[SetupAssistantWebView] Failed to start Google sign-in: \(error)", context: "SetupAssistant")
                dispatchActionResult(requestId: requestId, status: "failed", message: "I couldn’t start Google sign-in.")
            }
        }
    }

    func handleAccountOpenPaymentSetup(requestId: String?) {
        guard let url = URL(string: SetupAccountLinks.paymentSetupURLString) else {
            dispatchActionResult(requestId: requestId, status: "failed", message: "The payment setup address is invalid.")
            return
        }
        NSWorkspace.shared.open(url)
        dispatchActionResult(
            requestId: requestId,
            status: "executed",
            message: "Opened the payment page in your browser.",
            resultPayload: ["url": SetupAccountLinks.paymentSetupURLString]
        )
    }

    /// Re-reads the signed-in account from the auth service; `refreshUserData` also pushes the token to the backend, which is what lets the backend's eligibility check see the account.
    func handleAccountRefresh(requestId: String?) {
        Task { @MainActor in
            guard AuthService.shared.isAuthenticated else {
                dispatchActionResult(requestId: requestId, status: "executed", message: "Not signed in yet.", resultPayload: accountStatePayload())
                return
            }
            do {
                try await AuthService.shared.refreshUserData()
                dispatchActionResult(requestId: requestId, status: "executed", message: "Account refreshed.", resultPayload: accountStatePayload())
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: error.localizedDescription)
            }
        }
    }

    @MainActor
    private func accountStatePayload() -> [String: Any] {
        [
            "isAuthenticated": AuthService.shared.isAuthenticated,
            "hasPaymentMethod": AuthService.shared.hasPaymentMethod,
        ]
    }
}
