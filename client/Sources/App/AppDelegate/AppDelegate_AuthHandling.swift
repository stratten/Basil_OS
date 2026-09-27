import AppKit
import Foundation

// MARK: - URL Scheme Handling (OAuth Callbacks)

extension AppDelegate {
    
    /// Handle incoming URLs from custom URL scheme (basil://)
    func application(_ application: NSApplication, open urls: [URL]) {
        NSLog("🚨🚨🚨 application(_:open:) CALLED with %d URLs", urls.count)
        DevLogger.shared.info("🚨 application(_:open:) called with \(urls.count) URLs", context: "AppDelegate")
        
        guard !urls.isEmpty else {
            NSLog("🚨🚨🚨 URLs array is EMPTY!")
            DevLogger.shared.warning("🚨 URLs array is empty!", context: "AppDelegate")
            return
        }
        
        NSLog("🚨🚨🚨 About to start processing URLs...")
        DevLogger.shared.info("🚨 About to start processing URLs...", context: "AppDelegate")
        
        NSLog("🚨🚨🚨 Starting enumeration of %d URLs", urls.count)
        for (index, url) in urls.enumerated() {
            NSLog("🚨🚨🚨 Processing URL [%d]: %@", index, url.absoluteString)
            DevLogger.shared.info("🚨 Processing URL [\(index)]: \(url.absoluteString)", context: "AppDelegate")
            handleIncomingURL(url)
            NSLog("🚨🚨🚨 Successfully processed URL [%d]", index)
            DevLogger.shared.info("🚨 Successfully processed URL [\(index)]", context: "AppDelegate")
        }
        
        NSLog("🚨🚨🚨 application(_:open:) FINISHED processing all URLs")
        DevLogger.shared.info("🚨 application(_:open:) finished processing \(urls.count) URLs", context: "AppDelegate")
    }
    
    private func handleIncomingURL(_ url: URL) {
        NSLog("🚨🚨🚨 ENTERED handleIncomingURL with URL: %@", url.absoluteString)
        DevLogger.shared.info("🔵 ENTERED handleIncomingURL", context: "AppDelegate")
        
        #if DEBUG
        NSLog("🚨🚨🚨 URL scheme: %@, host: %@, path: %@", url.scheme ?? "nil", url.host ?? "nil", url.path)
        DevLogger.shared.info("Received URL: \(url.absoluteString)", context: "AppDelegate")
        DevLogger.shared.info("🔵 CHECKPOINT 1: After first log", context: "AppDelegate")
        DevLogger.shared.info("URL scheme: \(url.scheme ?? "nil")", context: "AppDelegate")
        DevLogger.shared.info("URL host: \(url.host ?? "nil")", context: "AppDelegate")
        DevLogger.shared.info("URL path: \(url.path)", context: "AppDelegate")
        #endif
        
        guard url.scheme == "basil" else {
            #if DEBUG
            DevLogger.shared.error("URL scheme is not 'basil', ignoring", context: "AppDelegate")
            #endif
            return
        }
        
        // Handle auth callback: basil://auth/callback?access_token=...&refresh_token=...
        if url.host == "auth" && url.path == "/callback" {
            #if DEBUG
            DevLogger.shared.info("Detected auth callback, processing...", context: "AppDelegate")
            #endif
            handleAuthCallback(url)
            return
        }

        // Handle MCP connection completion: basil://mcp/connection_complete?status=ok&connection_id=...
        // The Connections settings tab observes the resulting notification
        // and refreshes its list. The token itself is delivered separately
        // over the WebSocket bridge (mcp_token_store), so this handler only
        // needs to surface success/error metadata to the UI.
        if url.host == "mcp" && url.path == "/connection_complete" {
            #if DEBUG
            DevLogger.shared.info("Detected MCP connection callback, posting notification...", context: "AppDelegate")
            #endif
            handleMCPConnectionComplete(url)
            return
        }

        // Handle Slack OAuth PKCE callback: basil://mcp/slack_oauth_callback?code=...&state=...
        // Slack requires a pre-registered redirect URI and does not
        // support Dynamic Client Registration, so the redirect target
        // is this fixed custom URI handled by the desktop client.
        // The client forwards `code` and `state` to the local Python
        // backend, which exchanges them, persists metadata, and pushes
        // tokens into Keychain over the WebSocket bridge.
        if url.host == "mcp" && url.path == "/slack_oauth_callback" {
            #if DEBUG
            DevLogger.shared.info("Detected Slack OAuth callback, forwarding to local backend...", context: "AppDelegate")
            #endif
            handleSlackOAuthCallback(url)
            return
        }

        #if DEBUG
        DevLogger.shared.warning("URL host/path did not match any known callback (host: \(url.host ?? "nil"), path: \(url.path))", context: "AppDelegate")
        #endif
    }

    private func handleMCPConnectionComplete(_ url: URL) {
        var info: [String: Any] = [:]
        if let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
           let queryItems = components.queryItems {
            for item in queryItems where item.value != nil {
                info[item.name] = item.value!
            }
        }
        if info["status"] == nil {
            info["status"] = "ok"
        }
        NotificationCenter.default.post(
            name: .mcpConnectionCompleted,
            object: nil,
            userInfo: info
        )
    }

    private func handleSlackOAuthCallback(_ url: URL) {
        var code: String?
        var state: String?
        var slackError: String?
        var slackErrorDescription: String?

        if let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
           let queryItems = components.queryItems {
            for item in queryItems {
                switch item.name {
                case "code": code = item.value
                case "state": state = item.value
                case "error": slackError = item.value
                case "error_description": slackErrorDescription = item.value
                default: break
                }
            }
        }

        if let slackError = slackError {
            let message = slackErrorDescription ?? slackError
            DevLogger.shared.warning(
                "[AppDelegate] Slack OAuth returned error: \(slackError) - \(slackErrorDescription ?? "")",
                context: "AppDelegate"
            )
            NotificationCenter.default.post(
                name: .mcpConnectionCompleted,
                object: nil,
                userInfo: [
                    "status": "error",
                    "message": message,
                    "connector_id": "slack",
                ]
            )
            return
        }

        guard let code = code, let state = state else {
            DevLogger.shared.error(
                "[AppDelegate] Slack OAuth callback missing code or state",
                context: "AppDelegate"
            )
            NotificationCenter.default.post(
                name: .mcpConnectionCompleted,
                object: nil,
                userInfo: [
                    "status": "error",
                    "message": "Slack did not return a usable authorization code.",
                    "connector_id": "slack",
                ]
            )
            return
        }

        Task { @MainActor in
            do {
                let response = try await APIClient.shared.completeSlackOAuth(state: state, code: code)
                var info: [String: Any] = [
                    "status": response.status,
                    "connector_id": "slack",
                ]
                if let connection = response.connection {
                    info["connection_id"] = connection.id
                }
                if let message = response.message {
                    info["message"] = message
                }
                if info["status"] == nil {
                    info["status"] = "ok"
                }
                NotificationCenter.default.post(
                    name: .mcpConnectionCompleted,
                    object: nil,
                    userInfo: info
                )
            } catch {
                DevLogger.shared.error(
                    "[AppDelegate] Failed to complete Slack OAuth: \(error.localizedDescription)",
                    context: "AppDelegate"
                )
                NotificationCenter.default.post(
                    name: .mcpConnectionCompleted,
                    object: nil,
                    userInfo: [
                        "status": "error",
                        "message": "Slack sign-in could not be completed: \(error.localizedDescription)",
                        "connector_id": "slack",
                    ]
                )
            }
        }
    }
    
    private func handleAuthCallback(_ url: URL) {
        NSLog("🚨🚨🚨 ENTERED handleAuthCallback")
        #if DEBUG
        DevLogger.shared.info("handleAuthCallback called with URL: \(url.absoluteString)", context: "AppDelegate")
        #endif
        
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let queryItems = components.queryItems else {
            NSLog("🚨🚨🚨 FAILED to parse URL components or query items")
            #if DEBUG
            DevLogger.shared.error("Invalid auth callback URL - failed to parse URLComponents or queryItems", context: "AppDelegate")
            #endif
            return
        }
        
        NSLog("🚨🚨🚨 Found %d query items", queryItems.count)
        
        #if DEBUG
        DevLogger.shared.info("Found \(queryItems.count) query items", context: "AppDelegate")
        for item in queryItems {
            DevLogger.shared.info("Query param: \(item.name) = \(item.value?.prefix(20) ?? "nil")...", context: "AppDelegate")
        }
        #endif
        
        // Extract tokens from URL
        var accessToken: String?
        var refreshToken: String?
        var expiresIn: Int = 900
        
        for item in queryItems {
            switch item.name {
            case "access_token":
                accessToken = item.value
            case "refresh_token":
                refreshToken = item.value
            case "expires_in":
                if let value = item.value, let intValue = Int(value) {
                    expiresIn = intValue
                }
            default:
                break
            }
        }
        
        guard let access = accessToken, let refresh = refreshToken else {
            NSLog("🚨🚨🚨 MISSING TOKENS - accessToken: %@, refreshToken: %@", accessToken != nil ? "present" : "MISSING", refreshToken != nil ? "present" : "MISSING")
            #if DEBUG
            DevLogger.shared.error("Missing tokens in auth callback - accessToken: \(accessToken != nil ? "present" : "MISSING"), refreshToken: \(refreshToken != nil ? "present" : "MISSING")", context: "AppDelegate")
            #endif
            return
        }
        
        NSLog("🚨🚨🚨 TOKENS EXTRACTED - accessToken length: %d, refreshToken length: %d", access.count, refresh.count)
        #if DEBUG
        DevLogger.shared.info("Auth callback received with tokens - accessToken length: \(access.count), refreshToken length: \(refresh.count)", context: "AppDelegate")
        #endif
        
        // Complete the OAuth flow
        Task {
            NSLog("🚨🚨🚨 Starting OAuth completion Task")
            do {
                #if DEBUG
                DevLogger.shared.info("🔐 Starting OAuth completion with tokens...", context: "AppDelegate")
                #endif
                
                // Create tokens and complete auth
                let tokens = AuthTokens(
                    accessToken: access,
                    refreshToken: refresh,
                    tokenType: "bearer",
                    expiresIn: expiresIn
                )
                
                NSLog("🚨🚨🚨 Calling AuthService.completeOAuthWithTokens...")
                #if DEBUG
                DevLogger.shared.info("🔐 Calling completeOAuthWithTokens...", context: "AppDelegate")
                #endif
                
                // Store tokens and fetch user
                try await AuthService.shared.completeOAuthWithTokens(tokens)
                NSLog("🚨🚨🚨 completeOAuthWithTokens SUCCEEDED")
                
                #if DEBUG
                DevLogger.shared.info("✅ OAuth completed successfully via URL callback", context: "AppDelegate")
                #endif
            } catch {
                NSLog("🚨🚨🚨 ERROR in completeOAuthWithTokens: %@", error.localizedDescription)
                NSLog("🚨🚨🚨 Error type: %@", String(describing: type(of: error)))
                #if DEBUG
                DevLogger.shared.error("❌ Failed to complete OAuth: \(error)", context: "AppDelegate")
                DevLogger.shared.error("❌ Error type: \(type(of: error))", context: "AppDelegate")
                if let nsError = error as NSError? {
                    NSLog("🚨🚨🚨 NSError domain: %@, code: %d", nsError.domain, nsError.code)
                    NSLog("🚨🚨🚨 NSError userInfo: %@", String(describing: nsError.userInfo))
                    DevLogger.shared.error("❌ NSError domain: \(nsError.domain), code: \(nsError.code)", context: "AppDelegate")
                    DevLogger.shared.error("❌ NSError userInfo: \(nsError.userInfo)", context: "AppDelegate")
                }
                #endif
            }
        }
    }
}

