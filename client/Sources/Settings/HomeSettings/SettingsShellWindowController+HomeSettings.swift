import AppKit
import Foundation

extension SettingsShellWindowController {
    func wireHomeSettingsWebView(_ webView: ReactHomeSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadHomeSettingsAndSendInit() }
        }
        webView.onUpdateToggle = { [weak self] requestId, field, value in
            Task { @MainActor in await self?.performHomeToggleUpdate(requestId: requestId, field: field, value: value) }
        }
        webView.onUpdateSelectedModel = { [weak self] requestId, modelId in
            Task { @MainActor in await self?.performHomeSelectedModelUpdate(requestId: requestId, modelId: modelId) }
        }
        webView.onUpdateSelectedTranscriptionModel = { [weak self] requestId, modelId in
            Task { @MainActor in await self?.performHomeSelectedTranscriptionModelUpdate(requestId: requestId, modelId: modelId) }
        }
        webView.onOpenSetupAssistant = { [weak self] requestId in
            self?.performHomeOpenSetupAssistant(requestId: requestId)
        }
        webView.onOpenPowerUserGuide = { [weak self] requestId in
            self?.performHomeOpenPowerUserGuide(requestId: requestId)
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[HOME_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadHomeSettingsAndSendInit() async {
        homeLoadGeneration += 1
        let generation = homeLoadGeneration
        let fields = await buildHomeSettingsFields()
        guard generation == homeLoadGeneration, let webView = homeWebView else { return }
        webView.sendInit(fields: fields)
    }

    private func performHomeToggleUpdate(requestId: String, field: ReactHomeQuickToggleField, value: Bool) async {
        let succeeded = await applyHomeToggle(field: field, value: value)
        homeLoadGeneration += 1
        let generation = homeLoadGeneration
        let fields = await buildHomeSettingsFields()
        guard generation == homeLoadGeneration, let webView = homeWebView else { return }
        webView.sendSnapshot(fields: fields)
        webView.sendIntentResult(
            requestId: requestId,
            status: succeeded ? "success" : "error",
            message: succeeded ? nil : Self.homeToggleFailureMessage(for: field)
        )
    }

    private func applyHomeToggle(field: ReactHomeQuickToggleField, value: Bool) async -> Bool {
        switch field {
        case .enableMonitoringAtStartup:
            return await putHomeBehaviorFlag(key: "enable_monitoring_at_startup", value: value)
        case .enableVoiceListenerAtStartup:
            return await putHomeBehaviorFlag(key: "enable_voice_listener_at_startup", value: value)
        case .startActivityCaptureAtLaunch:
            do {
                _ = try await APIClient.shared.updateActivityCaptureStartAtStartup(value)
                return true
            } catch {
                return false
            }
        case .startMeetingDetectionAtLaunch:
            do {
                let update = value
                    ? MeetingDetectionSettingsUpdate(enabled: true, startAtStartup: true)
                    : MeetingDetectionSettingsUpdate(startAtStartup: false)
                _ = try await APIClient.shared.updateMeetingDetectionSettings(update)
                return true
            } catch {
                return false
            }
        case .activityCaptureEnabled:
            await activityCaptureViewModel.loadActivityCaptureSettings()
            activityCaptureViewModel.statusMessage = nil
            await activityCaptureViewModel.updateAutomaticCaptureEnabled(value)
            return activityCaptureViewModel.statusMessage?.contains("Error") != true
        case .meetingDetectionEnabled:
            await meetingDetectionViewModel.load()
            guard meetingDetectionViewModel.statusMessage?.contains("Error") != true else { return false }
            meetingDetectionViewModel.statusMessage = nil
            await meetingDetectionViewModel.updateEnabled(value)
            return meetingDetectionViewModel.statusMessage?.contains("Error") != true
        case .proactiveSuggestionsEnabled:
            await proactiveSuggestionsViewModel.load()
            guard proactiveSuggestionsViewModel.statusMessage?.contains("Error") != true else { return false }
            proactiveSuggestionsViewModel.statusMessage = nil
            await proactiveSuggestionsViewModel.updateAmbientSuggestionsEnabled(value)
            return proactiveSuggestionsViewModel.statusMessage?.contains("Error") != true
        }
    }

    private func putHomeBehaviorFlag(key: String, value: Bool) async -> Bool {
        do {
            let data = try JSONSerialization.data(withJSONObject: [key: value])
            let responseData = try await APIClient.shared.put("/settings/behavior", data: data)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            struct BehaviorSettingsUpdateResponse: Codable { let status: String; let updatedSettings: BehaviorSettings }
            let response = try decoder.decode(BehaviorSettingsUpdateResponse.self, from: responseData)
            APIClient.shared.cacheBehaviorSettings(response.updatedSettings)
            return true
        } catch {
            return false
        }
    }

    private func performHomeSelectedModelUpdate(requestId: String, modelId: String) async {
        guard let webView = homeWebView else { return }
        let isAvailable = reasoningDefaultsViewModel.localModels.contains { $0.id == modelId }
            || (reasoningDefaultsViewModel.useApiModels
                && (reasoningDefaultsViewModel.apiModels + reasoningDefaultsViewModel.customModels).contains { $0.id == modelId })
        guard isAvailable else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That reasoning model is no longer available.")
            return
        }
        await reasoningDefaultsViewModel.updateSelectedModel(modelId)
        let succeeded = reasoningDefaultsViewModel.selectedModelId == modelId
        homeLoadGeneration += 1
        let generation = homeLoadGeneration
        let fields = await buildHomeSettingsFields()
        guard generation == homeLoadGeneration else { return }
        webView.sendSnapshot(fields: fields)
        webView.sendIntentResult(
            requestId: requestId,
            status: succeeded ? "success" : "error",
            message: succeeded ? nil : "Failed to update the default reasoning model."
        )
    }

    private func performHomeSelectedTranscriptionModelUpdate(requestId: String, modelId: String) async {
        guard let webView = homeWebView else { return }
        let availableModels = await TranscriptionModelOption.loadAll().allOptions
        guard availableModels.contains(where: { $0.id == modelId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That transcription model is no longer available.")
            return
        }

        do {
            _ = try await APIClient.shared.swapTranscriptionModel(modelId)
        } catch {
            webView.sendIntentResult(
                requestId: requestId,
                status: "error",
                message: "Failed to activate the transcription model: \(error.localizedDescription)"
            )
            return
        }

        homeLoadGeneration += 1
        let generation = homeLoadGeneration
        let fields = await buildHomeSettingsFields()
        guard generation == homeLoadGeneration else { return }
        webView.sendSnapshot(fields: fields)
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private func performHomeOpenSetupAssistant(requestId: String) {
        guard let webView = homeWebView else { return }
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Unable to open the Setup Assistant.")
            return
        }
        appDelegate.presentSetupAssistantWindowFromDelegate()
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private func performHomeOpenPowerUserGuide(requestId: String) {
        guard let webView = homeWebView else { return }
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Unable to open the Capabilities Guide.")
            return
        }
        appDelegate.presentPowerUserGuideWindowFromDelegate()
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private static func homeToggleFailureMessage(for field: ReactHomeQuickToggleField) -> String {
        switch field {
        case .enableMonitoringAtStartup, .enableVoiceListenerAtStartup:
            return "Failed to update startup behavior."
        case .startActivityCaptureAtLaunch:
            return "Failed to update Activity Capture startup preference."
        case .startMeetingDetectionAtLaunch:
            return "Failed to update Meeting Detection startup preference."
        case .activityCaptureEnabled:
            return "Failed to update Activity Capture."
        case .meetingDetectionEnabled:
            return "Failed to update Meeting Detection."
        case .proactiveSuggestionsEnabled:
            return "Failed to update Proactive Suggestions."
        }
    }
}

extension SettingsShellWindowController {
    /// Aggregates a fresh, partial-success Home snapshot. Failed sources make only their own card unavailable.
    func buildHomeSettingsFields() async -> HomeSettingsFields {
        let permissionsSnapshot = await SetupPermissionsStatusEvaluator.currentStatus()
        let permissionsGrantedCount = [
            permissionsSnapshot.microphone,
            permissionsSnapshot.accessibility,
            permissionsSnapshot.inputMonitoring,
            permissionsSnapshot.screenRecording,
            permissionsSnapshot.appleEvents,
        ].filter { $0 == "granted" }.count

        async let setupAssistantStateLoad: Void = homeSetupAssistantPendingStateModel.loadFromBackend()
        async let behaviorData: Data? = try? APIClient.shared.get("/settings/behavior")
        async let activityCaptureSettings: ActivityCaptureSettingsData? = try? APIClient.shared.getActivityCaptureSettings()
        async let meetingDetectionSettings: MeetingDetectionSettingsData? = try? APIClient.shared.getMeetingDetectionSettings()
        async let proactiveSuggestionsSettings: AmbientSuggestionSettingsData? = try? APIClient.shared.getAmbientSuggestionSettings()
        async let reasoningModelsLoad: Void = reasoningDefaultsViewModel.loadReasoningModels()
        async let transcriptionModelsLoad: TranscriptionModelOption.LoadResult = TranscriptionModelOption.loadAll()

        let (
            _,
            loadedBehaviorData,
            loadedActivityCaptureSettings,
            loadedMeetingDetectionSettings,
            loadedProactiveSuggestionsSettings,
            _,
            loadedTranscriptionModels
        ) = await (
            setupAssistantStateLoad,
            behaviorData,
            activityCaptureSettings,
            meetingDetectionSettings,
            proactiveSuggestionsSettings,
            reasoningModelsLoad,
            transcriptionModelsLoad
        )
        let setupAssistantStateAvailable = homeSetupAssistantPendingStateModel.lastLoadError == nil

        var enableMonitoringAtStartup = false
        var enableVoiceListenerAtStartup = false
        var behaviorSettingsAvailable = false
        if let loadedBehaviorData {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            struct BehaviorSettingsResponse: Codable { let status: String; let settings: BehaviorSettings }
            if let settings = try? decoder.decode(BehaviorSettingsResponse.self, from: loadedBehaviorData).settings {
                enableMonitoringAtStartup = settings.enableMonitoringAtStartup
                enableVoiceListenerAtStartup = settings.enableVoiceListenerAtStartup
                behaviorSettingsAvailable = true
            }
        }
        let startActivityCaptureAtLaunch = loadedActivityCaptureSettings?.startAtStartup ?? false
        let startMeetingDetectionAtLaunch = loadedMeetingDetectionSettings?.startAtStartup ?? false

        return HomeSettingsFields(
            setupAssistantPending: homeSetupAssistantPendingStateModel.shouldShowSettingsResumeCard,
            setupAssistantCompleted: homeSetupAssistantPendingStateModel.hasCompletedSetupAssistant,
            setupAssistantStateAvailable: setupAssistantStateAvailable,
            permissionsGrantedCount: permissionsGrantedCount,
            permissionsTotalCount: 5,
            enableMonitoringAtStartup: enableMonitoringAtStartup,
            enableVoiceListenerAtStartup: enableVoiceListenerAtStartup,
            startActivityCaptureAtLaunch: startActivityCaptureAtLaunch,
            startMeetingDetectionAtLaunch: startMeetingDetectionAtLaunch,
            backgroundBehaviorAvailable: behaviorSettingsAvailable,
            activityCaptureEnabled: loadedActivityCaptureSettings?.activityCaptureEnabled ?? false,
            activityCaptureAvailable: loadedActivityCaptureSettings != nil,
            meetingDetectionEnabled: loadedMeetingDetectionSettings?.enabled ?? false,
            meetingDetectionAvailable: loadedMeetingDetectionSettings != nil,
            proactiveSuggestionsEnabled: loadedProactiveSuggestionsSettings?.enabled ?? false,
            proactiveSuggestionsAvailable: loadedProactiveSuggestionsSettings != nil,
            localModels: reasoningDefaultsViewModel.localModels,
            apiModels: reasoningDefaultsViewModel.apiModels,
            customModels: reasoningDefaultsViewModel.customModels,
            selectedModelId: reasoningDefaultsViewModel.selectedModelId,
            useApiModels: reasoningDefaultsViewModel.useApiModels,
            reasoningModelsAvailable: reasoningDefaultsViewModel.error == nil,
            localTranscriptionModels: loadedTranscriptionModels.localModels,
            apiTranscriptionModels: loadedTranscriptionModels.apiModels,
            selectedTranscriptionModelId: loadedTranscriptionModels.currentModelId,
            transcriptionModelsAvailable: true
        )
    }
}
