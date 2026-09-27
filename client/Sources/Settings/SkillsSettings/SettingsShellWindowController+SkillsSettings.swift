import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireSkillsSettingsWebView(_ webView: ReactSkillsSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadSkillsSettingsAndSendInit() }
        }
        webView.onRequestUpdateSkillAfterTaskEnabled = { [weak self] requestId, enabled in
            self?.performSkillsAction(requestId: requestId) { await $0.updateSkillAfterTaskEnabled(enabled) }
        }
        webView.onRequestUpdateSkillDailyEnabled = { [weak self] requestId, enabled in
            self?.performSkillsAction(requestId: requestId) { await $0.updateSkillDailyEnabled(enabled) }
        }
        webView.onRequestUpdateSkillDailyTimeLocal = { [weak self] requestId, time in
            self?.performSkillsAction(requestId: requestId) { await $0.updateSkillDailyTimeLocal(time) }
        }
        webView.onRequestUpdateSkillProcessingModel = { [weak self] requestId, modelId in
            guard let self, self.isSkillProcessingModelAvailable(modelId) else {
                self?.rejectSkillsRequest(requestId: requestId, message: "The selected evaluator model is unavailable.")
                return
            }
            self.performSkillsAction(requestId: requestId) { await $0.updateSkillProcessingModel(modelId) }
        }
        webView.onRequestUpdateSkillReconciliationMinInstances = { [weak self] requestId, minInstances in
            guard let self, !self.skillsViewModel.reconciliationActive else {
                self?.rejectSkillsRequest(requestId: requestId, message: "Reconciliation settings are unavailable while the reconciliation workspace is open.")
                return
            }
            guard (1...20).contains(minInstances) else {
                self.rejectSkillsRequest(requestId: requestId, message: "The reconciliation threshold must be between 1 and 20 observations.")
                return
            }
            self.performSkillsAction(requestId: requestId) { await $0.updateSkillReconciliationMinInstances(minInstances) }
        }
        webView.onRequestDeclineCandidate = { [weak self] requestId, id in
            guard let self else { return }
            guard !self.skillsViewModel.reconciliationActive else {
                self.rejectSkillsRequest(requestId: requestId, message: "Skill candidates are locked while the reconciliation workspace is open.")
                return
            }
            guard self.skillsViewModel.skillCandidates.contains(where: { $0.id == id }) else {
                self.rejectSkillsRequest(requestId: requestId, message: "That skill candidate is no longer available.")
                return
            }
            self.performSkillsAction(requestId: requestId) { await $0.declineCandidate(id: id) }
        }
        webView.onRequestDeleteSkill = { [weak self] requestId, slug in
            self?.confirmAndDeleteSkill(requestId: requestId, slug: slug)
        }
        webView.onRequestRunIntelligenceNow = { [weak self] requestId in
            guard let self else { return }
            guard !self.skillsViewModel.reconciliationActive, !self.skillsViewModel.isRunningSkillsIntelligence else {
                self.rejectSkillsRequest(requestId: requestId, message: "Skill intelligence is already running or locked by the reconciliation workspace.")
                return
            }
            self.performSkillsAction(requestId: requestId) { await $0.runIntelligenceNow() }
        }
        webView.onOpenSkillCandidate = { [weak self] id in
            self?.openSkillCandidate(id)
        }
        webView.onOpenSkill = { [weak self] slug in
            self?.openSkill(slug)
        }
        webView.onOpenReconciliationWorkspace = { [weak self] in
            self?.openSkillsReconciliationWorkspace()
        }
        webView.onFocusReconciliationWorkspace = {
            ReconciliationWorkspaceLauncher.shared.focusOrReopen()
        }
    }

    private func loadSkillsSettingsAndSendInit() async {
        skillsLoadGeneration += 1
        let generation = skillsLoadGeneration
        async let modelsLoad: Void = skillsViewModel.loadReasoningModels()
        async let skillsLoad: Void = skillsViewModel.loadSkillsState()
        _ = await (modelsLoad, skillsLoad)
        guard generation == skillsLoadGeneration else { return }
        skillsWebView?.sendInit(viewModel: skillsViewModel)
    }

    private func performSkillsAction(
        requestId: String,
        action: @escaping (ReasoningSettingsViewModel) async -> Void
    ) {
        Task { @MainActor in
            skillsLoadGeneration += 1
            let vm = skillsViewModel
            vm.skillsStatusMessage = nil
            await action(vm)
            let messageAfter = vm.skillsStatusMessage
            let failed = messageAfter?.contains("Error") ?? false
            skillsWebView?.sendSnapshot(viewModel: vm)
            if failed {
                skillsWebView?.sendIntentResult(requestId: requestId, status: "error", message: messageAfter)
            } else {
                skillsWebView?.sendIntentResult(requestId: requestId, status: "success", message: messageAfter)
            }
        }
    }

    private func confirmAndDeleteSkill(requestId: String, slug: String) {
        guard !skillsViewModel.reconciliationActive else {
            rejectSkillsRequest(requestId: requestId, message: "Saved skills are locked while the reconciliation workspace is open.")
            return
        }
        guard let skill = skillsViewModel.savedSkills.first(where: { $0.slug == slug }) else {
            rejectSkillsRequest(requestId: requestId, message: "That saved skill is no longer available.")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Delete \"\(skill.title)\"?"
        alert.informativeText = "This removes the saved skill. This cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Delete Skill")
        alert.addButton(withTitle: "Cancel")
        let response = alert.runModal()
        guard response == .alertFirstButtonReturn else {
            skillsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            return
        }
        performSkillsAction(requestId: requestId) { await $0.deleteSkill(slug: slug) }
    }

    private func isSkillProcessingModelAvailable(_ modelId: String?) -> Bool {
        guard let modelId else { return true }
        return skillsViewModel.availableSkillProcessingModels.contains { $0.id == modelId }
    }

    private func rejectSkillsRequest(requestId: String, message: String) {
        skillsWebView?.sendSnapshot(viewModel: skillsViewModel)
        skillsWebView?.sendIntentResult(requestId: requestId, status: "error", message: message)
    }

    private func openSkillCandidate(_ id: String) {
        guard !skillsViewModel.reconciliationActive else { return }
        guard skillsViewModel.skillCandidates.contains(where: { $0.id == id }) else { return }
        ProfileEditorLauncher.shared.open(.skillCandidate(id: id)) { [weak self] didChange in
            guard didChange, let self else { return }
            Task { @MainActor in
                await self.skillsViewModel.loadSkillsState()
                self.skillsWebView?.sendSnapshot(viewModel: self.skillsViewModel)
            }
        }
    }

    private func openSkill(_ slug: String) {
        guard !skillsViewModel.reconciliationActive else { return }
        guard skillsViewModel.savedSkills.contains(where: { $0.slug == slug }) else { return }
        ProfileEditorLauncher.shared.open(.skill(slug: slug)) { [weak self] didChange in
            guard didChange, let self else { return }
            Task { @MainActor in
                await self.skillsViewModel.loadSkillsState()
                self.skillsWebView?.sendSnapshot(viewModel: self.skillsViewModel)
            }
        }
    }

    private func openSkillsReconciliationWorkspace() {
        guard !skillsViewModel.reconciliationActive, !isOpeningSkillsReconciliationWorkspace else { return }
        isOpeningSkillsReconciliationWorkspace = true
        Task { @MainActor in
            await skillsViewModel.openReconciliationWorkspace { [weak self] in
                guard let self else { return }
                self.skillsWebView?.sendSnapshot(viewModel: self.skillsViewModel)
            }
            isOpeningSkillsReconciliationWorkspace = false
            skillsWebView?.sendSnapshot(viewModel: skillsViewModel)
        }
    }
}
