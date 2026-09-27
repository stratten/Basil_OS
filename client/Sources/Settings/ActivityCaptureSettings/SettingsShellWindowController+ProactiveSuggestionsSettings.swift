import Foundation

extension SettingsShellWindowController {
    func wireProactiveSuggestionsSettingsWebView(_ webView: ReactProactiveSuggestionsSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadProactiveSuggestionsSettingsAndSendInit() }
        }
        webView.onRequestUpdateEnabled = { [weak self] requestId, enabled in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionsEnabled(enabled)
            }
        }
        webView.onRequestUpdateMode = { [weak self] requestId, mode in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionMode(mode)
            }
        }
        webView.onRequestUpdateFrequencySeconds = { [weak self] requestId, seconds in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionFrequencySeconds(seconds)
            }
        }
        webView.onRequestUpdateEvaluationModel = { [weak self] requestId, modelId in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionEvaluationModel(modelId)
            }
        }
        webView.onRequestUpdateMinimumConfidence = { [weak self] requestId, confidence in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionMinimumConfidence(confidence)
            }
        }
        webView.onRequestUpdateCooldownMinutes = { [weak self] requestId, minutes in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionCooldownMinutes(minutes)
            }
        }
        webView.onRequestUpdateEnabledCapability = { [weak self] requestId, capability, enabled in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionEnabledCapability(capability, enabled: enabled)
            }
        }
        webView.onRequestUpdateAutoExecuteCapability = { [weak self] requestId, capability, enabled in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                await vm.updateAmbientSuggestionAutoExecuteCapability(capability, enabled: enabled)
            }
        }
        webView.onRequestUpdateExcludedAppNames = { [weak self] requestId, names in
            self?.performProactiveSuggestionsUpdate(requestId: requestId) { vm in
                vm.excludedAppNamesText = names.joined(separator: "\n")
                await vm.updateAmbientSuggestionExcludedAppNames()
            }
        }
    }

    private func loadProactiveSuggestionsSettingsAndSendInit() async {
        proactiveSuggestionsLoadGeneration += 1
        let generation = proactiveSuggestionsLoadGeneration
        await proactiveSuggestionsViewModel.load()
        guard generation == proactiveSuggestionsLoadGeneration else { return }
        if proactiveSuggestionsViewModel.statusMessage?.contains("Error") == true {
            proactiveSuggestionsWebView?.sendLoadError(
                message: proactiveSuggestionsViewModel.statusMessage ?? "Failed to load Proactive Suggestions settings."
            )
            return
        }
        proactiveSuggestionsWebView?.sendInit(viewModel: proactiveSuggestionsViewModel)
    }

    private func performProactiveSuggestionsUpdate(
        requestId: String,
        apply: @escaping (AmbientSuggestionSettingsViewModel) async -> Void
    ) {
        Task { @MainActor in
            let vm = proactiveSuggestionsViewModel
            vm.statusMessage = nil
            await apply(vm)
            let failed = vm.statusMessage?.contains("Error") == true
            proactiveSuggestionsWebView?.sendSnapshot(viewModel: vm)
            if failed {
                proactiveSuggestionsWebView?.sendIntentResult(requestId: requestId, status: "error", message: vm.statusMessage)
            } else {
                proactiveSuggestionsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            }
        }
    }
}
