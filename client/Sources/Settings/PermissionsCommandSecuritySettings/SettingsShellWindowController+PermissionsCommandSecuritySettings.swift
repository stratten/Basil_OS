import AppKit
import Foundation

extension SettingsShellWindowController {
    func wirePermissionsCommandSecurityWebView(_ webView: ReactPermissionsCommandSecurityWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadPermissionsCommandSecurityAndSendInit() }
        }
        webView.onRequestUpdateApprovalSetting = { [weak self] requestId, patch in
            Task { @MainActor in await self?.applyPermissionsCommandSecurityPatch(requestId: requestId, patch: patch) }
        }
        webView.onRequestAddWhitelistPattern = { [weak self] requestId, pattern, patternType, description in
            self?.performPermissionsCommandSecurityAddPattern(requestId: requestId, pattern: pattern, patternType: patternType, description: description)
        }
        webView.onRequestUpdateWhitelistPattern = { [weak self] requestId, id, pattern, patternType, description in
            self?.performPermissionsCommandSecurityUpdatePattern(requestId: requestId, id: id, pattern: pattern, patternType: patternType, description: description)
        }
        webView.onRequestDeleteWhitelistPattern = { [weak self] requestId, id in
            self?.performPermissionsCommandSecurityDeletePattern(requestId: requestId, id: id)
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[PERMISSIONS_COMMAND_SECURITY] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadPermissionsCommandSecurityAndSendInit() async {
        guard let webView = permissionsCommandSecurityWebView else { return }
        permissionsCommandSecurityLoadGeneration += 1
        let generation = permissionsCommandSecurityLoadGeneration
        let vm = permissionsSettingsViewModel
        await vm.loadApprovalData()
        guard generation == permissionsCommandSecurityLoadGeneration else { return }
        if let error = vm.errorMessage {
            webView.sendLoadError(message: error)
            return
        }
        webView.sendInit(viewModel: vm)
    }

    private static func whitelistValidationError(pattern: String, patternType: String) -> String? {
        guard !pattern.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return "Pattern cannot be empty."
        }
        guard ["exact", "prefix", "regex"].contains(patternType) else {
            return "Unrecognized pattern type."
        }
        if patternType == "regex" {
            do {
                _ = try NSRegularExpression(pattern: pattern, options: [])
            } catch {
                return "Invalid regular expression: \(error.localizedDescription)"
            }
        }
        return nil
    }

    private func applyPermissionsCommandSecurityPatch(requestId: String, patch: PermissionsCommandSecurityPatch) async {
        guard let webView = permissionsCommandSecurityWebView else { return }
        if let validationError = Self.approvalSettingsValidationError(for: patch) {
            webView.sendSnapshot(viewModel: permissionsSettingsViewModel)
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        let vm = permissionsSettingsViewModel
        permissionsCommandSecurityLoadGeneration += 1
        vm.errorMessage = nil
        await vm.updateApprovalSettings(patch.updateRequest())
        let actionError = vm.errorMessage
        let actionSucceeded = actionError == nil && Self.patchApplied(patch, to: vm.approvalSettings)
        await vm.loadApprovalData()
        webView.sendSnapshot(viewModel: vm)
        webView.sendIntentResult(
            requestId: requestId,
            status: actionSucceeded ? "success" : "error",
            message: actionSucceeded ? nil : actionError ?? "Failed to update the command approval setting."
        )
    }

    private static func approvalSettingsValidationError(for patch: PermissionsCommandSecurityPatch) -> String? {
        if patch.isEmpty {
            return "Choose a command approval setting to update."
        }
        if let approvalMode = patch.approvalMode, ExecutionApprovalSettings.ApprovalMode(rawValue: approvalMode) == nil {
            return "Unrecognized approval mode."
        }
        if let timeoutBehavior = patch.timeoutBehavior, ExecutionApprovalSettings.TimeoutBehavior(rawValue: timeoutBehavior) == nil {
            return "Unrecognized timeout behavior."
        }
        if let seconds = patch.approvalTimeoutSeconds, !(30...600).contains(seconds) || seconds % 30 != 0 {
            return "Approval timeout must be between 30 and 600 seconds in 30-second increments."
        }
        return nil
    }

    private static func patchApplied(_ patch: PermissionsCommandSecurityPatch, to settings: ExecutionApprovalSettings?) -> Bool {
        guard let settings else { return false }
        if let approvalMode = patch.approvalMode, settings.approvalMode.rawValue != approvalMode { return false }
        if let safeExecutionMode = patch.safeExecutionMode, settings.safeExecutionMode != safeExecutionMode { return false }
        if let autoApproveReadOnly = patch.autoApproveReadOnly, settings.autoApproveReadOnly != autoApproveReadOnly { return false }
        if let blockDangerousPatterns = patch.blockDangerousPatterns, settings.blockDangerousPatterns != blockDangerousPatterns { return false }
        if let approvalTimeoutSeconds = patch.approvalTimeoutSeconds, settings.approvalTimeoutSeconds != approvalTimeoutSeconds { return false }
        if let timeoutBehavior = patch.timeoutBehavior, settings.timeoutBehavior.rawValue != timeoutBehavior { return false }
        return true
    }

    private func performPermissionsCommandSecurityAddPattern(requestId: String, pattern: String, patternType: String, description: String) {
        guard let webView = permissionsCommandSecurityWebView else { return }
        if let validationError = Self.whitelistValidationError(pattern: pattern, patternType: patternType) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        Task { @MainActor in
            let vm = permissionsSettingsViewModel
            permissionsCommandSecurityLoadGeneration += 1
            await vm.addWhitelistPattern(pattern: pattern, patternType: patternType, description: description)
            let actionError = vm.errorMessage
            let actionSucceeded = actionError == nil && vm.whitelistPatterns.contains { $0.pattern == pattern && $0.patternType == patternType && $0.description == description }
            await vm.loadApprovalData()
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? nil : actionError ?? "Failed to add the whitelist pattern."
            )
        }
    }

    private func performPermissionsCommandSecurityUpdatePattern(requestId: String, id: String, pattern: String, patternType: String, description: String) {
        guard let webView = permissionsCommandSecurityWebView else { return }
        if let validationError = Self.whitelistValidationError(pattern: pattern, patternType: patternType) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        Task { @MainActor in
            let vm = permissionsSettingsViewModel
            permissionsCommandSecurityLoadGeneration += 1
            await vm.updateWhitelistPattern(id: id, pattern: pattern, patternType: patternType, description: description)
            let actionError = vm.errorMessage
            let actionSucceeded = actionError == nil && vm.whitelistPatterns.contains { $0.id == id && $0.pattern == pattern && $0.patternType == patternType && $0.description == description }
            await vm.loadApprovalData()
            webView.sendSnapshot(viewModel: vm)
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? nil : actionError ?? "Failed to update the whitelist pattern."
            )
        }
    }

    private func performPermissionsCommandSecurityDeletePattern(requestId: String, id: String) {
        guard let webView = permissionsCommandSecurityWebView else { return }
        guard let window else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "The Settings window is unavailable.")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Remove Whitelisted Command?"
        alert.informativeText = "This command pattern will no longer be auto-approved. You can re-add it later if needed."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Remove")
        alert.addButton(withTitle: "Cancel")

        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn else {
                webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            Task { @MainActor in
                guard let self else { return }
                let vm = self.permissionsSettingsViewModel
                self.permissionsCommandSecurityLoadGeneration += 1
                await vm.removeWhitelistPattern(id: id)
                let actionError = vm.errorMessage
                let actionSucceeded = actionError == nil && !vm.whitelistPatterns.contains { $0.id == id }
                await vm.loadApprovalData()
                webView.sendSnapshot(viewModel: vm)
                webView.sendIntentResult(
                    requestId: requestId,
                    status: actionSucceeded ? "success" : "error",
                    message: actionSucceeded ? nil : actionError ?? "Failed to remove the whitelist pattern."
                )
            }
        }
    }
}
