import SwiftUI
import AppKit

// `TranscriptionModelOption` was promoted to a top-level shared file at
// `client/Sources/App/Transcription/TranscriptionModelOption.swift`
// so the in-widget picker and the Settings tab can share one type. The
// struct's field shape is unchanged, so call sites in this file continue
// to compile against it directly.

@MainActor
final class TranscriptionSettingsViewModel: ObservableObject {
    @Published private(set) var availableModels: [String] = []
    @Published private(set) var apiModels: [TranscriptionModelOption] = []
    @Published private(set) var localModels: [TranscriptionModelOption] = []
    @Published var selectedModel: String = ""
    @Published var selectedUnloadDelay: TranscriptionModelUnloadDelay = .minutes1
    @Published var autoPasteTranscription: Bool = false
    @Published var autoCloseOnPaste: Bool = false
    @Published var transcriptionLanguage: String = "en"
    @Published var enablePushToTalk: Bool = false
    @Published var pushToTalkThresholdMs: Int = 750
    // Meeting post-processing automation defaults.
    @Published var autoRetranscribeOnStop: Bool = false
    @Published var autoRetranscribeDuringRecording: Bool = false
    @Published var retranscribeWindowMinutes: Int = 10
    @Published var autoAnalyzeOnComplete: Bool = false
    @Published var autoAnalyzeModes: [String] = []
    @Published var autoAnalyzeCustomInstructions: String = ""
    @Published var autoAnalyzeTiming: String = "after"
    @Published var textReplacements: [TranscriptionTextReplacementRule] = []
    // Meeting Detection startup preference. Owned by MeetingDetectionSettings
    // (loaded/saved via /settings/meeting-detection) and surfaced here so the
    // user can opt into auto-starting the detector at launch from this tab.
    @Published var startMeetingDetectionAtStartup: Bool = false

    private let api = APIClient.shared
    
    init() {
        #if DEBUG
        DevLogger.shared.info("Initializing TranscriptionSettingsViewModel", context: "TranscriptionSettings")
        #endif

        #if DEBUG
        DevLogger.shared.info("Settings initialized - autoPaste: \(autoPasteTranscription), autoCloseOnPaste: \(autoCloseOnPaste), pushToTalk: \(enablePushToTalk)", context: "TranscriptionSettings")
        #endif
        
        // Only models need to be loaded async since they can change
        Task {
            await loadModels()
        }
    }
    
    func loadModels() async {
        var localModelNames: [String] = []
        var localOptions: [TranscriptionModelOption] = []
        var apiOptions: [TranscriptionModelOption] = []
        
        // Load local installed models
        do {
            let data = try await api.get("/models/installed")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            struct ModelVariant: Codable {
                let name: String
                let capabilities: [String]?
                let valid: Bool?
            }

            struct ModelType: Codable {
                let variants: [String: ModelVariant]
            }

            let response = try decoder.decode([String: ModelType].self, from: data)

            for (_, modelType) in response {
                for (_, variant) in modelType.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("transcription") {
                        localModelNames.append(variant.name)
                        localOptions.append(TranscriptionModelOption(
                            id: variant.name,
                            displayName: variant.name,
                            isApiModel: false,
                            provider: nil
                        ))
                    }
                }
            }
        } catch {
            DevLogger.shared.error("Failed to load local transcription models: \(error)", context: "TranscriptionSettings")
        }
        
        // Load API transcription models
        do {
            let apiResponse = try await api.getApiTranscriptionModels()
            if apiResponse.apiTranscriptionModelsEnabled {
                for model in apiResponse.models {
                    apiOptions.append(TranscriptionModelOption(
                        id: model.id,
                        displayName: model.displayName,
                        isApiModel: true,
                        provider: model.provider
                    ))
                }
            }
        } catch {
            DevLogger.shared.error("Failed to load API transcription models: \(error)", context: "TranscriptionSettings")
        }
        
        self.localModels = localOptions.sorted(by: { $0.displayName < $1.displayName })
        self.apiModels = apiOptions
        
        // Build combined list for backwards compatibility
        var allIds = localModelNames.sorted()
        allIds.append(contentsOf: apiOptions.map { $0.id })
        self.availableModels = allIds
        
        if !allIds.isEmpty && selectedModel.isEmpty {
            self.selectedModel = allIds[0]
        }
        
        // Load current model setting
        if let modelSettings = try? await loadModelSettings() {
            self.selectedModel = modelSettings.transcriptionModel
        }
    }
    
    @discardableResult
    func loadSettings() async -> Bool {
        var didLoad = false
        do {
            // TranscriptionSettings defines explicit snake_case CodingKeys, so
            // this endpoint must decode with default keys.
            let response = try await api.get(
                "/settings/transcription",
                decoding: TranscriptionSettingsResponse.self,
                keyDecodingStrategy: .useDefaultKeys
            )
            let settings = response.settings
            applyTranscriptionSettings(settings)
            api.cacheTranscriptionSettings(settings)
            didLoad = true

            #if DEBUG
            DevLogger.shared.info("Settings reloaded - autoPaste: \(autoPasteTranscription), pushToTalk: \(enablePushToTalk), threshold: \(pushToTalkThresholdMs)ms, autoAnalyze: \(autoAnalyzeOnComplete), autoAnalyzeModes: \(autoAnalyzeModes)", context: "TranscriptionSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to reload settings: \(error)", context: "TranscriptionSettings")
            #endif
        }

        // Meeting Detection startup lives on a separate preference model, so it
        // is fetched independently (mirroring how the Hotkey tab cross-reads
        // /settings/behavior) and never touches the transcription payload above.
        // Its own success/failure is unrelated to this method's returned Bool.
        await loadMeetingDetectionStartup()
        return didLoad
    }

    /// Load just the "start meeting detection at launch" flag from the
    /// meeting-detection preferences. Failures keep the current default.
    func loadMeetingDetectionStartup() async {
        do {
            let settings = try await api.getMeetingDetectionSettings()
            startMeetingDetectionAtStartup = settings.startAtStartup
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load meeting detection startup flag: \(error)", context: "TranscriptionSettings")
            #endif
        }
    }

    /// Persist the "start meeting detection at launch" flag.
    ///
    /// This mirrors the hotkey "enable monitoring at startup" model as a single
    /// switch: turning it on also enables Meeting Detection (so the launch
    /// auto-start is not blocked by a disabled feature) but does NOT start the
    /// monitor in the current session. Turning it off only clears the startup
    /// flag and leaves the feature's enabled state untouched. The partial
    /// (exclude_unset) update means no other meeting-detection field is
    /// disturbed; we then refresh the menu/status-bar state like the dedicated
    /// Meeting Detection tab does.
    @discardableResult
    func updateMeetingDetectionStartup(_ enabled: Bool) async -> Bool {
        let previousValue = startMeetingDetectionAtStartup
        startMeetingDetectionAtStartup = enabled
        do {
            let update = enabled
                ? MeetingDetectionSettingsUpdate(enabled: true, startAtStartup: true)
                : MeetingDetectionSettingsUpdate(startAtStartup: false)
            _ = try await api.updateMeetingDetectionSettings(update)
            NotificationCenter.default.post(name: .meetingDetectionSettingsChanged, object: nil)
            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                await appDelegate.statusBarManager?.refreshMeetingDetectionState()
            }
            return true
        } catch {
            startMeetingDetectionAtStartup = previousValue
            #if DEBUG
            DevLogger.shared.error("Failed to update meeting detection startup flag: \(error)", context: "TranscriptionSettings")
            #endif
            return false
        }
    }
    
    private func loadModelSettings() async throws -> TranscriptionSettingsModel {
        let data = try await api.get("/settings/models")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        
        // Backend now returns wrapped response: { "status": "success", "settings": {...} }
        struct ModelSettingsResponse: Codable {
            let status: String
            let settings: TranscriptionSettingsModel
        }
        
        let response = try decoder.decode(ModelSettingsResponse.self, from: data)
        return response.settings
    }

    private func applyTranscriptionSettings(_ settings: TranscriptionSettings) {
        if let delay = TranscriptionModelUnloadDelay(rawValue: settings.modelUnloadDelay) {
            selectedUnloadDelay = delay
        }
        autoPasteTranscription = settings.autoPaste
        autoCloseOnPaste = settings.autoCloseOnPaste
        transcriptionLanguage = settings.language
        selectedModel = settings.selectedModel
        enablePushToTalk = settings.enablePushToTalk
        pushToTalkThresholdMs = settings.pushToTalkThresholdMs
        autoRetranscribeOnStop = settings.autoRetranscribeOnStop
        autoRetranscribeDuringRecording = settings.autoRetranscribeDuringRecording
        retranscribeWindowMinutes = Int((Double(settings.retranscribeWindowSeconds) / 60.0).rounded())
        autoAnalyzeOnComplete = settings.autoAnalyzeOnComplete
        autoAnalyzeModes = settings.autoAnalyzeModes
        autoAnalyzeCustomInstructions = settings.autoAnalyzeCustomInstructions
        autoAnalyzeTiming = settings.autoAnalyzeTiming
        textReplacements = settings.textReplacements
    }

    private func localTranscriptionSettingsSnapshot() -> TranscriptionSettings {
        TranscriptionSettings(
            modelUnloadDelay: selectedUnloadDelay.rawValue,
            autoPaste: autoPasteTranscription,
            autoCloseOnPaste: autoCloseOnPaste,
            language: transcriptionLanguage,
            selectedModel: selectedModel,
            widgetSize: nil,
            widgetPosition: nil,
            isWidgetMinimized: false,
            enablePushToTalk: enablePushToTalk,
            pushToTalkThresholdMs: pushToTalkThresholdMs,
            autoRetranscribeOnStop: autoRetranscribeOnStop,
            autoRetranscribeDuringRecording: autoRetranscribeDuringRecording,
            retranscribeWindowSeconds: retranscribeWindowMinutes * 60,
            autoAnalyzeOnComplete: autoAnalyzeOnComplete,
            autoAnalyzeModes: autoAnalyzeModes,
            autoAnalyzeCustomInstructions: autoAnalyzeCustomInstructions,
            autoAnalyzeTiming: autoAnalyzeTiming,
            textReplacements: textReplacements
        )
    }

    private func fetchCurrentTranscriptionSettings() async -> TranscriptionSettings? {
        do {
            let data = try await api.get("/settings/transcription")
            if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
                return response.settings
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to get current settings: \(error)", context: "TranscriptionSettings")
            #endif
        }
        return nil
    }

    /// Local view-model values with server widget geometry and automation merged
    /// when available (prior behavior for behavior-toggle updates).
    private func settingsBaseForPersist(from server: TranscriptionSettings?) -> TranscriptionSettings {
        let local = localTranscriptionSettingsSnapshot()
        guard let server else { return local }
        return local.applying(
            widgetSize: server.widgetSize,
            widgetPosition: server.widgetPosition,
            isWidgetMinimized: server.isWidgetMinimized,
            enablePushToTalk: server.enablePushToTalk,
            pushToTalkThresholdMs: server.pushToTalkThresholdMs,
            autoRetranscribeOnStop: server.autoRetranscribeOnStop,
            autoRetranscribeDuringRecording: server.autoRetranscribeDuringRecording,
            retranscribeWindowSeconds: server.retranscribeWindowSeconds,
            autoAnalyzeOnComplete: server.autoAnalyzeOnComplete,
            autoAnalyzeModes: server.autoAnalyzeModes,
            autoAnalyzeCustomInstructions: server.autoAnalyzeCustomInstructions,
            autoAnalyzeTiming: server.autoAnalyzeTiming,
            textReplacements: server.textReplacements
        )
    }

    /// Local automation + behavior fields; only widget geometry comes from server.
    private func localWithServerWidget(from server: TranscriptionSettings?) -> TranscriptionSettings {
        let local = localTranscriptionSettingsSnapshot()
        guard let server else { return local }
        return local.applying(
            widgetSize: server.widgetSize,
            widgetPosition: server.widgetPosition,
            isWidgetMinimized: server.isWidgetMinimized
        )
    }

    @discardableResult
    private func putTranscriptionSettings(_ settings: TranscriptionSettings) async -> Bool {
        do {
            let data = try JSONEncoder().encode(settings)
            _ = try await api.put("/settings/transcription", data: data)
            api.cacheTranscriptionSettings(settings)
            return true
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to save transcription settings: \(error)", context: "TranscriptionSettings")
            #endif
            return false
        }
    }
    
    @discardableResult
    func updateUnloadDelay(_ delay: TranscriptionModelUnloadDelay) async -> Bool {
        let previousDelay = selectedUnloadDelay
        selectedUnloadDelay = delay

        let server = await fetchCurrentTranscriptionSettings()
        let settings = settingsBaseForPersist(from: server).applying(modelUnloadDelay: delay.rawValue)
        let success = await putTranscriptionSettings(settings)
        if !success {
            selectedUnloadDelay = previousDelay
        }

        #if DEBUG
        if success {
            DevLogger.shared.info("Updated unload delay to \(delay.displayName)", context: "TranscriptionSettings")
        }
        #endif
        return success
    }

    @discardableResult
    func updateAutoPaste(_ enabled: Bool) async -> Bool {
        let previousValue = autoPasteTranscription
        autoPasteTranscription = enabled

        let server = await fetchCurrentTranscriptionSettings()
        let settings = settingsBaseForPersist(from: server).applying(autoPaste: enabled)
        let success = await putTranscriptionSettings(settings)
        if !success {
            autoPasteTranscription = previousValue
        }

        #if DEBUG
        if success {
            DevLogger.shared.info("Updated autoPaste to \(enabled)", context: "TranscriptionSettings")
        }
        #endif
        return success
    }

    @discardableResult
    func updateAutoCloseOnPaste(_ enabled: Bool) async -> Bool {
        #if DEBUG
        DevLogger.shared.info("Updating autoCloseOnPaste to \(enabled)", context: "TranscriptionSettings")
        #endif

        let previousValue = autoCloseOnPaste
        autoCloseOnPaste = enabled

        let server = await fetchCurrentTranscriptionSettings()
        let settings = settingsBaseForPersist(from: server).applying(autoCloseOnPaste: enabled)
        let success = await putTranscriptionSettings(settings)

        guard success else {
            autoCloseOnPaste = previousValue
            return false
        }

        #if DEBUG
        DevLogger.shared.info("Settings update successful", context: "TranscriptionSettings")
        #endif

        do {
            let freshData = try await api.get("/settings/transcription")
            if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: freshData) {
                #if DEBUG
                DevLogger.shared.info("Verified autoCloseOnPaste is now \(response.settings.autoCloseOnPaste)", context: "TranscriptionSettings")
                #endif
                api.cacheTranscriptionSettings(response.settings)
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Error verifying settings: \(error)", context: "TranscriptionSettings")
            #endif
        }
        return true
    }
    
    @discardableResult
    func updateSelectedModel(_ model: String) async -> Bool {
        let previousModel = selectedModel
        selectedModel = model

        let server = await fetchCurrentTranscriptionSettings()
        let transcriptionSettings = settingsBaseForPersist(from: server).applying(selectedModel: model)
        let success = await putTranscriptionSettings(transcriptionSettings)
        guard success else {
            selectedModel = previousModel
            return false
        }

        // Best-effort mirror into /settings/models so other surfaces that
        // read the canonical model id stay in sync. This has never had its
        // own success signal and continues not to affect the returned Bool.
        do {
            let modelData = try await api.get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase

            struct ModelSettingsResponse: Codable {
                let status: String
                let settings: TranscriptionSettingsModel
            }
            let modelResponse = try decoder.decode(ModelSettingsResponse.self, from: modelData)
            let modelSettings = modelResponse.settings

            let updatedModelSettings = TranscriptionSettingsModel(
                persistenceDuration: modelSettings.persistenceDuration,
                visionModel: modelSettings.visionModel,
                languageModel: modelSettings.languageModel,
                reasoningModel: modelSettings.reasoningModel,
                transcriptionModel: model
            )

            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            if let encodedModelData = try? encoder.encode(updatedModelSettings) {
                _ = try? await api.put("/settings/models", data: encodedModelData)
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to update model settings: \(error)", context: "TranscriptionSettings")
            #endif
        }
        return success
    }

    @discardableResult
    func updatePushToTalk(_ enabled: Bool) async -> Bool {
        let previousValue = enablePushToTalk
        enablePushToTalk = enabled

        let server = await fetchCurrentTranscriptionSettings()
        let settings = settingsBaseForPersist(from: server).applying(enablePushToTalk: enabled)
        let success = await putTranscriptionSettings(settings)
        if !success {
            enablePushToTalk = previousValue
        }

        #if DEBUG
        if success {
            DevLogger.shared.info("Updated push-to-talk enabled to \(enabled)", context: "TranscriptionSettings")
        }
        #endif
        return success
    }

    @discardableResult
    func updatePushToTalkThreshold(_ thresholdMs: Int) async -> Bool {
        let previousValue = pushToTalkThresholdMs
        pushToTalkThresholdMs = thresholdMs

        let server = await fetchCurrentTranscriptionSettings()
        let settings = settingsBaseForPersist(from: server).applying(pushToTalkThresholdMs: thresholdMs)
        let success = await putTranscriptionSettings(settings)
        if !success {
            pushToTalkThresholdMs = previousValue
        }

        #if DEBUG
        if success {
            DevLogger.shared.info("Updated push-to-talk threshold to \(thresholdMs)ms", context: "TranscriptionSettings")
        }
        #endif
        return success
    }

    // MARK: - Meeting Automation Defaults

    @discardableResult
    func updateAutoRetranscribeOnStop(_ enabled: Bool) async -> Bool {
        autoRetranscribeOnStop = enabled
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateAutoRetranscribeDuringRecording(_ enabled: Bool) async -> Bool {
        autoRetranscribeDuringRecording = enabled
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateRetranscribeWindowMinutes(_ minutes: Int) async -> Bool {
        retranscribeWindowMinutes = max(1, minutes)
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateAutoAnalyzeOnComplete(_ enabled: Bool) async -> Bool {
        autoAnalyzeOnComplete = enabled
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateAutoAnalyzeMode(_ mode: String, isOn: Bool) async -> Bool {
        if isOn {
            if !autoAnalyzeModes.contains(mode) { autoAnalyzeModes.append(mode) }
        } else {
            autoAnalyzeModes.removeAll { $0 == mode }
        }
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateAutoAnalyzeCustomInstructions(_ text: String) async -> Bool {
        autoAnalyzeCustomInstructions = text
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateAutoAnalyzeTiming(_ timing: String) async -> Bool {
        autoAnalyzeTiming = timing
        return await persistAutomationSettings()
    }

    @discardableResult
    func updateTextReplacements(_ rules: [TranscriptionTextReplacementRule]) async -> Bool {
        let previousRules = textReplacements
        textReplacements = rules
        let success = await persistAutomationSettings()
        if !success {
            textReplacements = previousRules
        }
        return success
    }

    /// Persist the meeting-automation defaults, preserving the rest of the
    /// transcription settings (widget geometry, model, etc.) read from the
    /// server so a save here does not clobber unrelated fields. Returns
    /// whether the PUT succeeded so callers (native SwiftUI call sites and
    /// the React bridge) can surface a real failure instead of assuming
    /// success.
    @discardableResult
    private func persistAutomationSettings() async -> Bool {
        let server = await fetchCurrentTranscriptionSettings()
        let settings = localWithServerWidget(from: server)
        let success = await putTranscriptionSettings(settings)

        #if DEBUG
        if success {
            DevLogger.shared.info("Updated meeting automation defaults", context: "TranscriptionSettings")
        }
        #endif
        return success
    }

}

// MARK: - Model Types
struct TranscriptionSettingsModel: Codable {
    let persistenceDuration: Int
    let visionModel: String
    let languageModel: String
    let reasoningModel: String
    let transcriptionModel: String
} 