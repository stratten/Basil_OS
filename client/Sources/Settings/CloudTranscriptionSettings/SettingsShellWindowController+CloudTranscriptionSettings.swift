import Foundation

extension SettingsShellWindowController {
    func wireCloudTranscriptionSettingsWebView(_ webView: ReactCloudTranscriptionWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadCloudTranscriptionAndSendState()
            }
        }
        webView.onRequestUpdateSettings = { [weak self] requestId, patch in
            self?.runCloudTranscriptionIntent(requestId: requestId, method: "PUT", path: "/settings", body: patch)
        }
        webView.onRequestSaveKey = { [weak self] requestId, provider, key in
            self?.runCloudTranscriptionIntent(requestId: requestId, method: "PUT", path: "/keys/\(provider)", body: ["api_key": key])
        }
        webView.onRequestRemoveKey = { [weak self] requestId, provider in
            self?.runCloudTranscriptionIntent(requestId: requestId, method: "DELETE", path: "/keys/\(provider)", body: nil)
        }
        webView.onRequestCheck = { [weak self] requestId, provider in
            self?.runCloudTranscriptionCheck(requestId: requestId, provider: provider)
        }
    }

    /// Runs requests one at a time in the order the page sent them, so quick successive changes cannot reach the backend out of order.
    private func enqueueCloudTranscriptionWork(_ work: @escaping @MainActor () async -> Void) {
        let previous = cloudTranscriptionRequestTail
        cloudTranscriptionRequestTail = Task { @MainActor in
            await previous?.value
            await work()
        }
    }

    private func loadCloudTranscriptionAndSendState() async {
        switch await APIClient.shared.sendCloudTranscriptionRequest(method: "GET", path: "") {
        case .success(let state):
            cloudTranscriptionWebView?.sendState(state)
        case .failure(let message):
            cloudTranscriptionWebView?.sendLoadError(message: message)
        }
    }

    /// Runs a settings or key request, pushes the backend's new state to the page, then reports the result for the request.
    private func runCloudTranscriptionIntent(requestId: String, method: String, path: String, body: [String: Any]?) {
        enqueueCloudTranscriptionWork { [weak self] in
            switch await APIClient.shared.sendCloudTranscriptionRequest(method: method, path: path, body: body) {
            case .success(let state):
                self?.cloudTranscriptionWebView?.sendState(state)
                self?.cloudTranscriptionWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            case .failure(let message):
                self?.cloudTranscriptionWebView?.sendIntentResult(requestId: requestId, status: "error", message: message)
            }
        }
    }

    /// The connection check sends no meeting audio. Its `ok` and `message` fields become the request result.
    private func runCloudTranscriptionCheck(requestId: String, provider: String) {
        enqueueCloudTranscriptionWork { [weak self] in
            switch await APIClient.shared.sendCloudTranscriptionRequest(method: "POST", path: "/check", body: ["provider": provider]) {
            case .success(let result):
                let ok = result["ok"] as? Bool ?? false
                let message = result["message"] as? String
                self?.cloudTranscriptionWebView?.sendIntentResult(requestId: requestId, status: ok ? "success" : "error", message: message)
            case .failure(let message):
                self?.cloudTranscriptionWebView?.sendIntentResult(requestId: requestId, status: "error", message: message)
            }
        }
    }
}
