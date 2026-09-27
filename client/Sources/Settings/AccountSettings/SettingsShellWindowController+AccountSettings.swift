import AppKit
import Combine
import Foundation

extension SettingsShellWindowController {
    func wireAccountSettingsWebView(_ webView: ReactAccountSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadAccountSettingsAndSendInit() }
        }
        webView.onRequestLogin = { [weak self] requestId, email, password in
            self?.performAccountLogin(requestId: requestId, email: email, password: password)
        }
        webView.onRequestSignup = { [weak self] requestId, email, password, confirmPassword in
            self?.performAccountSignup(requestId: requestId, email: email, password: password, confirmPassword: confirmPassword)
        }
        webView.onRequestGoogleSignIn = { [weak self] requestId in
            self?.performAccountGoogleSignIn(requestId: requestId)
        }
        webView.onRequestSignOut = { [weak self] requestId in
            self?.performAccountSignOut(requestId: requestId)
        }
        webView.onRequestSetApiKeyPreference = { [weak self] requestId, preference in
            self?.performAccountSetApiKeyPreference(requestId: requestId, preference: preference)
        }
        webView.onRequestPaymentSetup = { [weak self] requestId in
            self?.performAccountPaymentSetup(requestId: requestId)
        }
        webView.onRequestRefreshPaymentAndUsage = { [weak self] requestId in
            self?.performAccountRefreshPaymentAndUsage(requestId: requestId)
        }
        webView.onRequestDeleteAccount = { [weak self] requestId in
            self?.performAccountDeleteAccount(requestId: requestId)
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[ACCOUNT_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }

        // See settled decision 3: every `@Published` mutation on
        // `accountViewModel` (from a bridge action's own await, from
        // the async OAuth URL-scheme callback, or from a future
        // externally-triggered auth change) already fires this once
        // `loadData()` has run once and lazily subscribed to
        // `AuthService.shared` internally. Debounced to coalesce bursts
        // of related property changes (e.g. `loadFromAuthService()`
        // setting three `@Published` fields back-to-back) into one push.
        accountAuthObserverCancellable = accountViewModel.objectWillChange
            .debounce(for: .milliseconds(150), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self, let webView = self.accountWebView else { return }
                webView.sendSnapshot(viewModel: self.accountViewModel)
            }
    }

    private func loadAccountSettingsAndSendInit() async {
        accountLoadGeneration += 1
        let generation = accountLoadGeneration
        await accountViewModel.loadData()
        guard generation == accountLoadGeneration else { return }
        guard let webView = accountWebView else { return }
        webView.sendInit(viewModel: accountViewModel)
    }

    // Mirrors `PaymentSetupSheet.paymentURL` in the legacy
    // `AccountSettingsTab.swift` -- both leaves open the same
    // Stripe-hosted setup page in the system browser.
    private static let accountPaymentSetupURL = "https://basilauthservice-production.up.railway.app/web/payment"

    private func performAccountLogin(requestId: String, email: String, password: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            do {
                try await AuthService.shared.login(email: email, password: password)
                webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
                webView.sendSnapshot(viewModel: accountViewModel)
            } catch {
                webView.sendIntentResult(requestId: requestId, status: "error", message: error.localizedDescription)
            }
        }
    }

    private func performAccountSignup(requestId: String, email: String, password: String, confirmPassword: String) {
        guard let webView = accountWebView else { return }
        // Mirrors `LoginSignupSheet.submit`'s own guard -- native never
        // sends a mismatched/short password to `AuthService.register`.
        guard password == confirmPassword else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Passwords don't match")
            return
        }
        guard password.count >= 8 else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Password must be at least 8 characters")
            return
        }
        Task { @MainActor in
            do {
                try await AuthService.shared.register(email: email, password: password)
                webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
                webView.sendSnapshot(viewModel: accountViewModel)
            } catch {
                webView.sendIntentResult(requestId: requestId, status: "error", message: error.localizedDescription)
            }
        }
    }

    private func performAccountGoogleSignIn(requestId: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            do {
                let url = try await AuthService.shared.getGoogleAuthURL()
                NSWorkspace.shared.open(url)
                // Completion arrives asynchronously via the
                // `basil://auth/callback` URL scheme (decision 3) --
                // this intentResult only confirms the browser opened.
                webView.sendIntentResult(requestId: requestId, status: "success", message: "Complete sign-in in your browser, then return here.")
            } catch {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to start Google sign-in.")
            }
        }
    }

    private func performAccountSignOut(requestId: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            await accountViewModel.signOut()
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            webView.sendSnapshot(viewModel: accountViewModel)
        }
    }

    private func performAccountSetApiKeyPreference(requestId: String, preference: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            guard let parsed = APIKeyPreference(rawValue: preference) else {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "Unrecognized preference.")
                return
            }
            // Basil Cloud goes through the same gating
            // `selectBasilCloudAccess()` the native button uses (checks
            // trial balance, then requires auth + payment) -- see
            // settled decision 11.
            if parsed.isBasilCloudAlias {
                await accountViewModel.selectBasilCloudAccess()
            } else {
                accountViewModel.setAPIKeyPreference(parsed)
            }
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            webView.sendSnapshot(viewModel: accountViewModel)
        }
    }

    private func performAccountPaymentSetup(requestId: String) {
        guard let webView = accountWebView else { return }
        guard let url = URL(string: Self.accountPaymentSetupURL) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Invalid payment setup URL.")
            return
        }
        NSWorkspace.shared.open(url)
        webView.sendIntentResult(requestId: requestId, status: "success", message: "Opened payment setup in your browser. Refresh below once you're done.")
    }

    private func performAccountRefreshPaymentAndUsage(requestId: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            // See settled decision 12: `loadData()` re-runs
            // `loadPaymentMethod()`/`loadUsage()`, both of which already
            // swallow their own errors internally, matching native.
            await accountViewModel.loadData()
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            webView.sendSnapshot(viewModel: accountViewModel)
        }
    }

    private func performAccountDeleteAccount(requestId: String) {
        Task { @MainActor in
            guard let webView = accountWebView else { return }
            do {
                try await accountViewModel.deleteAccount()
                webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
                webView.sendSnapshot(viewModel: accountViewModel)
            } catch {
                // Surfaces `AuthError.accountDeletionBlocked`'s exact
                // server-provided reason verbatim (settled decision 1).
                webView.sendIntentResult(requestId: requestId, status: "error", message: error.localizedDescription)
            }
        }
    }
}
