import SwiftUI
import UniformTypeIdentifiers
@preconcurrency import WebKit

struct SetupAssistantWebView: NSViewRepresentable {
    var onRestartRequested: (() -> Void)?
    var onCloseRequested: (() -> Void)?
    var onMinimizeRequested: (() -> Void)?
    var onCollapseRequested: (() -> Void)?
    var onExpandRequested: (() -> Void)?
    var onCoordinatorReady: ((Coordinator) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(
            onRestartRequested: onRestartRequested,
            onCloseRequested: onCloseRequested,
            onMinimizeRequested: onMinimizeRequested,
            onCollapseRequested: onCollapseRequested,
            onExpandRequested: onExpandRequested
        )
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let config: [String: Any] = [
            "apiBaseUrl": APIClient.shared.baseURL,
            "theme": SetupAssistantThemePayload.theme(),
            "fonts": SetupAssistantThemePayload.fonts(),
        ]
        let configData = try? JSONSerialization.data(withJSONObject: config, options: [])
        let configJSON = configData.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        let configScript = WKUserScript(
            source: "window.basilSetupAssistantConfig = \(configJSON);",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(configScript)

        let consoleScript = WKUserScript(
            source: """
                (function() {
                    var originalLog = console.log;
                    var originalError = console.error;
                    var originalWarn = console.warn;
                    console.log = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'log', message: Array.from(arguments).join(' ')});
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'error', message: Array.from(arguments).join(' ')});
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'warn', message: Array.from(arguments).join(' ')});
                        originalWarn.apply(console, arguments);
                    };
                })();
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        )
        configuration.userContentController.addUserScript(consoleScript)
        configuration.userContentController.add(context.coordinator, name: "setupAssistant")
        configuration.userContentController.add(context.coordinator, name: "jsLog")

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")

        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        SetupWindowDragAreaInstaller.install(in: webView)
        context.coordinator.loadContent(in: webView)
        onCoordinatorReady?(context.coordinator)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler, AppearanceRefreshable {
        private var onRestartRequested: (() -> Void)?
        private var onCloseRequested: (() -> Void)?
        private var onMinimizeRequested: (() -> Void)?
        private var onCollapseRequested: (() -> Void)?
        private var onExpandRequested: (() -> Void)?
        private weak var webView: WKWebView?

        init(
            onRestartRequested: (() -> Void)?,
            onCloseRequested: (() -> Void)?,
            onMinimizeRequested: (() -> Void)?,
            onCollapseRequested: (() -> Void)?,
            onExpandRequested: (() -> Void)?
        ) {
            self.onRestartRequested = onRestartRequested
            self.onCloseRequested = onCloseRequested
            self.onMinimizeRequested = onMinimizeRequested
            self.onCollapseRequested = onCollapseRequested
            self.onExpandRequested = onExpandRequested
        }

        func loadContent(in webView: WKWebView) {
            self.webView = webView

            guard let resourceURL = Bundle.main.resourceURL else {
                DevLogger.shared.error("[SetupAssistantWebView] Could not get resource URL", context: "SetupAssistant")
                return
            }

            let webAssetsFolder = resourceURL.appendingPathComponent("SetupAssistantWebAssets")
            let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/setup-assistant.html")

            if FileManager.default.fileExists(atPath: htmlURL.path) {
                webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
            } else {
                DevLogger.shared.error("[SetupAssistantWebView] HTML file not found at \(htmlURL.path)", context: "SetupAssistant")
            }
        }

        func refreshAppearance() {
            let detail: [String: Any] = [
                "theme": SetupAssistantThemePayload.theme(),
                "fonts": SetupAssistantThemePayload.fonts(),
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: detail),
                  let json = String(data: data, encoding: .utf8) else {
                return
            }
            webView?.evaluateJavaScript(
                "window.basilSetupAssistantConfig = { ...(window.basilSetupAssistantConfig || {}), theme: \(json).theme, fonts: \(json).fonts }; window.dispatchEvent(new CustomEvent('setupAssistantThemeChanged', { detail: \(json) }));"
            )
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            if message.name == "jsLog" {
                handleLogMessage(message.body)
                return
            }

            guard message.name == "setupAssistant",
                  let body = message.body as? [String: Any],
                  let name = body["name"] as? String else {
                return
            }

            handleSetupAssistantMessage(
                name: name,
                payload: body["payload"] as? [String: Any],
                requestId: body["requestId"] as? String
            )
        }

        private func handleLogMessage(_ body: Any) {
            guard let log = body as? [String: String] else { return }
            let level = log["level"] ?? "log"
            let message = log["message"] ?? ""
            DevLogger.shared.info("[SetupAssistant JS \(level)] \(message)", context: "SetupAssistant")
        }

        private func handleSetupAssistantMessage(name: String, payload: [String: Any]?, requestId: String?) {
            switch name {
            case "setupAssistantReady":
                DevLogger.shared.info("[SetupAssistantWebView] Web UI ready", context: "SetupAssistant")
            case "openSystemSettings":
                openSystemSettings(payload: payload)
            case "restartApplication":
                onRestartRequested?()
            case "closeSetupAssistant":
                onCloseRequested?()
            case "minimizeSetupAssistant":
                onMinimizeRequested?()
            case "collapseSetupAssistant":
                onCollapseRequested?()
            case "expandSetupAssistant":
                onExpandRequested?()
            case "openConnectionAuth":
                startConnectionAuth(payload: payload, requestId: requestId)
            case "launchAgentTaskOffer":
                launchAgentTaskOffer(payload: payload, requestId: requestId)
            case "launchAssistantSessionOffer":
                launchAssistantSessionOffer(payload: payload, requestId: requestId)
            case "saveSetupReferencePdf":
                saveSetupReferencePdf(payload: payload, requestId: requestId)
            default:
                DevLogger.shared.warning("[SetupAssistantWebView] Unknown bridge action: \(name)", context: "SetupAssistant")
            }
        }

        private func openSystemSettings(payload: [String: Any]?) {
            let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy")!
            NSWorkspace.shared.open(url)
            DevLogger.shared.info("[SetupAssistantWebView] Opened System Settings for \(payload?["kind"] ?? "privacy")", context: "SetupAssistant")
        }

        private func saveSetupReferencePdf(payload: [String: Any]?, requestId: String?) {
            guard let payload,
                  let base64Pdf = payload["base64Pdf"] as? String,
                  let pdfData = Data(base64Encoded: base64Pdf) else {
                dispatchActionResult(
                    requestId: requestId,
                    status: "failed",
                    message: "I couldn't prepare that setup reference PDF."
                )
                return
            }

            let suggestedFilename = (
                payload["suggestedFilename"] as? String
            )?.trimmingCharacters(in: .whitespacesAndNewlines)
            let savePanel = NSSavePanel()
            savePanel.allowedContentTypes = [.pdf]
            if let suggestedFilename, !suggestedFilename.isEmpty {
                savePanel.nameFieldStringValue = suggestedFilename
            } else {
                savePanel.nameFieldStringValue = "Basil Setup Reference.pdf"
            }

            savePanel.begin { [weak self] response in
                guard let self else { return }
                guard response == .OK, let url = savePanel.url else {
                    self.dispatchActionResult(
                        requestId: requestId,
                        status: "executed",
                        message: "Save canceled.",
                        resultPayload: ["saved": false]
                    )
                    return
                }

                do {
                    try pdfData.write(to: url, options: .atomic)
                    self.dispatchActionResult(
                        requestId: requestId,
                        status: "executed",
                        message: "PDF saved.",
                        resultPayload: ["saved": true, "path": url.path]
                    )
                } catch {
                    DevLogger.shared.error("[SetupAssistantWebView] Failed to save setup reference PDF: \(error)", context: "SetupAssistant")
                    self.dispatchActionResult(
                        requestId: requestId,
                        status: "failed",
                        message: "I couldn't save that PDF: \(error.localizedDescription)"
                    )
                }
            }
        }

        private func startConnectionAuth(payload: [String: Any]?, requestId: String?) {
            guard let payload,
                  let serverUrl = payload["serverUrl"] as? String,
                  let friendlyName = payload["friendlyName"] as? String else {
                DevLogger.shared.warning("[SetupAssistantWebView] Missing connection auth payload", context: "SetupAssistant")
                dispatchActionResult(
                    requestId: requestId,
                    status: "failed",
                    message: "I couldn't start that connection — some required details were missing."
                )
                return
            }

            let connectorId = payload["connectorId"] as? String
            Task { @MainActor in
                do {
                    switch connectorId {
                    case "github":
                        let flow = try await APIClient.shared.startGitHubDeviceFlow(
                            serverUrl: serverUrl,
                            friendlyName: friendlyName
                        )
                        if let url = URL(string: flow.verificationUri) {
                            NSWorkspace.shared.open(url)
                        }
                        dispatchActionResult(
                            requestId: requestId,
                            status: "executed",
                            message: "I opened the GitHub authorization in your browser.",
                            resultPayload: ["connectorId": connectorId ?? "github"]
                        )
                        await pollGitHubDeviceFlow(deviceCode: flow.deviceCode, initialInterval: flow.interval)
                    case "slack":
                        // Slack PKCE: backend builds the URL using the
                        // configured client_id + basil://mcp/slack_oauth_callback
                        // redirect URI; AppDelegate completes the flow.
                        let response = try await APIClient.shared.startSlackOAuth(
                            serverUrl: serverUrl, friendlyName: friendlyName
                        )
                        guard let url = URL(string: response.authorizationUrl) else {
                            dispatchActionResult(requestId: requestId, status: "failed",
                                message: "Slack returned an invalid authorization URL.")
                            return
                        }
                        NSWorkspace.shared.open(url)
                        dispatchActionResult(requestId: requestId, status: "executed",
                            message: "I opened the Slack authorization in your browser.",
                            resultPayload: ["connectorId": "slack", "serverUrl": serverUrl])
                    default:
                        let url = try await APIClient.shared.startMCPOAuth(
                            serverUrl: serverUrl,
                            friendlyName: friendlyName
                        )
                        NSWorkspace.shared.open(url)
                        dispatchActionResult(
                            requestId: requestId,
                            status: "executed",
                            message: "I opened that connection's authorization in your browser.",
                            resultPayload: ["serverUrl": serverUrl]
                        )
                    }
                } catch {
                    DevLogger.shared.error("[SetupAssistantWebView] Failed to start connection auth: \(error)", context: "SetupAssistant")
                    dispatchActionResult(
                        requestId: requestId,
                        status: "failed",
                        message: "I couldn't start that connection: \(error.localizedDescription)"
                    )
                }
            }
        }

        private func launchAgentTaskOffer(payload: [String: Any]?, requestId: String?) {
            let offer = payload?["offer"] as? [String: Any]
            let prompt = (offer?["prompt"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let prompt, !prompt.isEmpty else {
                DevLogger.shared.warning("[SetupAssistantWebView] Missing task offer prompt", context: "SetupAssistant")
                dispatchActionResult(
                    requestId: requestId,
                    status: "failed",
                    message: "I didn't receive a prompt for that task, so I couldn't start it."
                )
                return
            }

            // Tasks launched from setup inherit the setup agent's chosen model
            // route (default = free proxy) so they don't silently fall back to
            // a user's preferred local reasoning model and overflow its context.
            // The backend setup runtime stamps model_id onto every
            // launch_agent_task receipt before it reaches the user.
            let offerModelId = (offer?["model_id"] as? String)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let resolvedModelId = (offerModelId?.isEmpty == false) ? offerModelId : nil

            let agentTaskId = UUID().uuidString
            AgentTaskResultPresentationRouter.installNewAgent(
                agentTaskId: agentTaskId,
                initialAgentTask: prompt
            )
            dispatchActionResult(
                requestId: requestId,
                status: "executed",
                message: "I handed that task to Paprika — I'll narrate the result when it's back.",
                resultPayload: ["agentTaskId": agentTaskId]
            )

            Task { @MainActor in
                do {
                    _ = try await APIClient.shared.processAgentTask(
                        prompt,
                        agentTaskId: agentTaskId,
                        modelId: resolvedModelId
                    )
                } catch {
                    DevLogger.shared.error("[SetupAssistantWebView] Failed to launch setup AgentTask: \(error)", context: "SetupAssistant")
                }
            }

            // Parallel poller that watches this launched task and pushes
            // progress + terminal observations back into the setup webview so
            // the setup agent can re-engage automatically (narrate the outcome,
            // suggest next steps). Polling-based by design - the setup webview
            // does not subscribe to the AgentTask WebSocket today and the
            // existing GET endpoint is already in use elsewhere.
            Task { @MainActor in
                await self.pollSetupAgentTask(agentTaskId: agentTaskId)
            }
        }

        private func launchAssistantSessionOffer(payload: [String: Any]?, requestId: String?) {
            let action = payload?["action"] as? [String: Any]
            let actionPayload = action?["payload"] as? [String: Any]
            let instruction = (
                actionPayload?["instruction"] as? String
                ?? actionPayload?["prompt"] as? String
                ?? "Help me with this."
            )
            let contextText = actionPayload?["contextText"] as? String
            let applicationName = actionPayload?["applicationName"] as? String

            // Assistant sessions launched from setup inherit the setup agent's
            // chosen model route (default = free proxy) so a Dill draft kicked
            // off during onboarding does not silently fall back to a user's
            // preferred local reasoning model and overflow its context. The
            // backend setup runtime stamps `model_id` onto every
            // launch_assistant_session payload alongside `source_email_id`
            // before it reaches the user, so we just need to forward it.
            let offerModelId = (actionPayload?["model_id"] as? String)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let resolvedModelId = (offerModelId?.isEmpty == false) ? offerModelId : nil

            // Unlike launch_agent_task (where the agentTaskId is minted
            // client-side and known synchronously), the AssistantSession id
            // is allocated by the backend inside the view-model flow.
            // Defer dispatchActionResult until `onSessionStarted` fires so
            // we can return the id to the frontend in `resultPayload`,
            // mirroring how Paprika returns `agentTaskId`. If the view
            // model never reaches `.running` within the safety window
            // below, we fall back to a failed dispatch so the frontend
            // doesn't hang in `executing` forever.
            var hasDispatchedResult = false
            let dispatchOnce: ((String, String, [String: Any]) -> Void) = { [weak self] status, message, resultPayload in
                guard !hasDispatchedResult else { return }
                hasDispatchedResult = true
                self?.dispatchActionResult(
                    requestId: requestId,
                    status: status,
                    message: message,
                    resultPayload: resultPayload
                )
            }

            AssistantSessionWindowController.showFromSetupAssistant(
                instruction: instruction,
                contextText: contextText,
                applicationName: applicationName,
                modelId: resolvedModelId,
                onSessionStarted: { sessionId in
                    // Be honest about what just happened: the assistant
                    // doesn't just open — it immediately fires the request
                    // using the grounding email body and the setup model.
                    // Returning `assistantSessionId` here is what enables
                    // the frontend to register the session for the
                    // re-engagement loop on terminal completion.
                    dispatchOnce(
                        "executed",
                        "I handed that to Dill — the draft will stream in shortly.",
                        ["assistantSessionId": sessionId]
                    )
                },
                onSessionTerminal: { [weak self] outcome in
                    // The bridge action-result is independent of the
                    // observation event; if for some reason the start
                    // callback never fired (e.g., session id allocation
                    // failed before .running was set), still resolve the
                    // pending action-result with a failure so the
                    // frontend's `executing` state doesn't get stuck.
                    if outcome.sessionId == nil {
                        dispatchOnce(
                            "failed",
                            outcome.errorMessage ?? "Dill couldn't start. Try again, or pick a different email.",
                            [:]
                        )
                    }
                    guard let sessionId = outcome.sessionId, !sessionId.isEmpty else {
                        DevLogger.shared.warning(
                            "[SetupAssistantWebView] Skipping assistant-session terminal observation: missing session id",
                            context: "SetupAssistant"
                        )
                        return
                    }
                    self?.emitAssistantSessionObservation(
                        assistantSessionId: sessionId,
                        kind: "terminal",
                        status: outcome.status,
                        resultText: outcome.resultText,
                        errorMessage: outcome.errorMessage
                    )
                }
            )

            // Safety net: if the view model never transitions to .running
            // within 30 seconds (network failure during start_from_text,
            // backend dead, etc.), resolve the pending action-result as
            // failed so the receipt button stops spinning. The observation
            // path is unaffected — if a session does eventually start
            // after this fallback fires, the observation will still flow
            // through normally and the worst case is a slightly stale
            // "failed" line in the conversation that the eventual terminal
            // observation can supersede.
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                if !hasDispatchedResult {
                    DevLogger.shared.warning(
                        "[SetupAssistantWebView] launch_assistant_session never reported a session id within 30s; dispatching failed result",
                        context: "SetupAssistant"
                    )
                    dispatchOnce(
                        "failed",
                        "Dill didn't get a chance to start — give it another try.",
                        [:]
                    )
                }
            }
        }

        private func dispatchActionResult(
            requestId: String?,
            status: String,
            message: String,
            resultPayload: [String: Any] = [:]
        ) {
            guard let requestId, let webView else { return }
            let detail: [String: Any] = [
                "requestId": requestId,
                "status": status,
                "message": message,
                "resultPayload": resultPayload
            ]

            guard let data = try? JSONSerialization.data(withJSONObject: detail),
                  let json = String(data: data, encoding: .utf8) else {
                DevLogger.shared.warning("[SetupAssistantWebView] Failed to encode setup action result", context: "SetupAssistant")
                return
            }

            webView.evaluateJavaScript(
                "window.dispatchEvent(new CustomEvent('setupAssistantActionResult', { detail: \(json) }));"
            )
        }

        /// Dispatch a `setupAssistantAssistantSessionObservation` custom
        /// event so the setup webview's observation listener can convert
        /// the Dill session's terminal state into an `execution_outcomes`
        /// entry for the setup agent to react to. Symmetric to
        /// `emitAgentTaskObservation`, just keyed on
        /// `assistantSessionId` and carrying a `resultText` field
        /// instead of `currentStep`/`resultMessage`.
        private func emitAssistantSessionObservation(
            assistantSessionId: String,
            kind: String,
            status: String,
            resultText: String?,
            errorMessage: String?
        ) {
            guard let webView else { return }
            var detail: [String: Any] = [
                "assistantSessionId": assistantSessionId,
                "kind": kind,
                "status": status
            ]
            if let resultText, !resultText.isEmpty { detail["resultText"] = resultText }
            if let errorMessage, !errorMessage.isEmpty { detail["errorMessage"] = errorMessage }

            guard let data = try? JSONSerialization.data(withJSONObject: detail),
                  let json = String(data: data, encoding: .utf8) else {
                DevLogger.shared.warning("[SetupAssistantWebView] Failed to encode assistant session observation", context: "SetupAssistant")
                return
            }

            webView.evaluateJavaScript(
                "window.dispatchEvent(new CustomEvent('setupAssistantAssistantSessionObservation', { detail: \(json) }));"
            )
        }

        private func emitAgentTaskObservation(
            agentTaskId: String,
            kind: String,
            status: String,
            currentStep: String?,
            resultMessage: String?,
            errorMessage: String?
        ) {
            guard let webView else { return }
            var detail: [String: Any] = [
                "agentTaskId": agentTaskId,
                "kind": kind,
                "status": status
            ]
            if let currentStep, !currentStep.isEmpty { detail["currentStep"] = currentStep }
            if let resultMessage, !resultMessage.isEmpty { detail["resultMessage"] = resultMessage }
            if let errorMessage, !errorMessage.isEmpty { detail["errorMessage"] = errorMessage }

            guard let data = try? JSONSerialization.data(withJSONObject: detail),
                  let json = String(data: data, encoding: .utf8) else {
                DevLogger.shared.warning("[SetupAssistantWebView] Failed to encode agent task observation", context: "SetupAssistant")
                return
            }

            webView.evaluateJavaScript(
                "window.dispatchEvent(new CustomEvent('setupAssistantAgentTaskObservation', { detail: \(json) }));"
            )
        }

        @MainActor
        private func pollSetupAgentTask(agentTaskId: String) async {
            // Backoff schedule: first three ticks at 2/4/8s to catch the fast
            // routing -> processing transition, then 10s steady state. Hard
            // ceiling of 10 minutes prevents a runaway poller if the task is
            // long-lived or stuck. Progress emissions are gated by a 10-second
            // minimum gap and a content-change check so we never spam the
            // setup agent with redundant turns.
            let terminalStatuses: Set<String> = ["completed", "failed", "canceled"]
            let stagedIntervalsNs: [UInt64] = [2_000_000_000, 4_000_000_000, 8_000_000_000]
            let steadyIntervalNs: UInt64 = 10_000_000_000
            let hardCeilingSeconds: TimeInterval = 600
            let progressFloorSeconds: TimeInterval = 10

            let startedAt = Date()
            var lastStatus: String? = nil
            var lastResultMessageSnapshot: String? = nil
            var lastProgressEmitAt: Date = .distantPast
            var tickIndex = 0

            while !Task.isCancelled {
                let sleepNs = tickIndex < stagedIntervalsNs.count
                    ? stagedIntervalsNs[tickIndex]
                    : steadyIntervalNs
                tickIndex += 1
                try? await Task.sleep(nanoseconds: sleepNs)

                if Date().timeIntervalSince(startedAt) > hardCeilingSeconds {
                    DevLogger.shared.warning(
                        "[SetupAssistantWebView] Stopping agent task poller for \(agentTaskId) after hard ceiling",
                        context: "SetupAssistant"
                    )
                    return
                }

                do {
                    let detail = try await APIClient.shared.getAgentTask(agentTaskId: agentTaskId)
                    let status = detail.status
                    let resultMessage = detail.resultMessage
                    let isTerminal = terminalStatuses.contains(status.lowercased())

                    if isTerminal {
                        let isFailure = status.lowercased() == "failed"
                        emitAgentTaskObservation(
                            agentTaskId: agentTaskId,
                            kind: "terminal",
                            status: status,
                            currentStep: nil,
                            resultMessage: resultMessage,
                            errorMessage: isFailure ? resultMessage : nil
                        )
                        return
                    }

                    let statusChanged = lastStatus != status
                    let messageChanged = lastResultMessageSnapshot != resultMessage
                    let pastFloor = Date().timeIntervalSince(lastProgressEmitAt) >= progressFloorSeconds
                    if (statusChanged || messageChanged) && pastFloor {
                        emitAgentTaskObservation(
                            agentTaskId: agentTaskId,
                            kind: "progress",
                            status: status,
                            currentStep: resultMessage,
                            resultMessage: nil,
                            errorMessage: nil
                        )
                        lastProgressEmitAt = Date()
                    }

                    lastStatus = status
                    lastResultMessageSnapshot = resultMessage
                } catch {
                    DevLogger.shared.warning(
                        "[SetupAssistantWebView] Polling failed for \(agentTaskId): \(error)",
                        context: "SetupAssistant"
                    )
                }
            }
        }

        @MainActor
        private func pollGitHubDeviceFlow(deviceCode: String, initialInterval: Int) async {
            var interval = max(initialInterval, 5)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(interval) * 1_000_000_000)
                do {
                    let response = try await APIClient.shared.pollGitHubDeviceFlow(deviceCode: deviceCode)
                    if response.status == "pending" {
                        interval = max(response.interval ?? interval, 5)
                        continue
                    }
                    if response.status == "ok", let connection = response.connection {
                        _ = try? await APIClient.shared.refreshMCPTools(connectionId: connection.id)
                    }
                    return
                } catch {
                    DevLogger.shared.error("[SetupAssistantWebView] GitHub device flow polling failed: \(error)", context: "SetupAssistant")
                    return
                }
            }
        }
    }
}

