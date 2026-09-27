import Foundation

struct HomeSettingsFields {
    let setupAssistantPending: Bool
    let setupAssistantStateAvailable: Bool
    let permissionsGrantedCount: Int
    let permissionsTotalCount: Int
    let enableMonitoringAtStartup: Bool
    let enableVoiceListenerAtStartup: Bool
    let startActivityCaptureAtLaunch: Bool
    let startMeetingDetectionAtLaunch: Bool
    let backgroundBehaviorAvailable: Bool
    let activityCaptureEnabled: Bool
    let activityCaptureAvailable: Bool
    let meetingDetectionEnabled: Bool
    let meetingDetectionAvailable: Bool
    let proactiveSuggestionsEnabled: Bool
    let proactiveSuggestionsAvailable: Bool
    let localModels: [ReasoningModelInfo]
    let apiModels: [ReasoningModelInfo]
    let customModels: [ReasoningModelInfo]
    let selectedModelId: String
    let useApiModels: Bool
    let reasoningModelsAvailable: Bool
    let localTranscriptionModels: [TranscriptionModelOption]
    let apiTranscriptionModels: [TranscriptionModelOption]
    let selectedTranscriptionModelId: String
    let transcriptionModelsAvailable: Bool

    init(
        setupAssistantPending: Bool,
        setupAssistantStateAvailable: Bool,
        permissionsGrantedCount: Int,
        permissionsTotalCount: Int,
        enableMonitoringAtStartup: Bool,
        enableVoiceListenerAtStartup: Bool,
        startActivityCaptureAtLaunch: Bool,
        startMeetingDetectionAtLaunch: Bool,
        backgroundBehaviorAvailable: Bool,
        activityCaptureEnabled: Bool,
        activityCaptureAvailable: Bool,
        meetingDetectionEnabled: Bool,
        meetingDetectionAvailable: Bool,
        proactiveSuggestionsEnabled: Bool,
        proactiveSuggestionsAvailable: Bool,
        localModels: [ReasoningModelInfo],
        apiModels: [ReasoningModelInfo],
        customModels: [ReasoningModelInfo],
        selectedModelId: String,
        useApiModels: Bool,
        reasoningModelsAvailable: Bool,
        localTranscriptionModels: [TranscriptionModelOption] = [],
        apiTranscriptionModels: [TranscriptionModelOption] = [],
        selectedTranscriptionModelId: String = "",
        transcriptionModelsAvailable: Bool = false
    ) {
        self.setupAssistantPending = setupAssistantPending
        self.setupAssistantStateAvailable = setupAssistantStateAvailable
        self.permissionsGrantedCount = permissionsGrantedCount
        self.permissionsTotalCount = permissionsTotalCount
        self.enableMonitoringAtStartup = enableMonitoringAtStartup
        self.enableVoiceListenerAtStartup = enableVoiceListenerAtStartup
        self.startActivityCaptureAtLaunch = startActivityCaptureAtLaunch
        self.startMeetingDetectionAtLaunch = startMeetingDetectionAtLaunch
        self.backgroundBehaviorAvailable = backgroundBehaviorAvailable
        self.activityCaptureEnabled = activityCaptureEnabled
        self.activityCaptureAvailable = activityCaptureAvailable
        self.meetingDetectionEnabled = meetingDetectionEnabled
        self.meetingDetectionAvailable = meetingDetectionAvailable
        self.proactiveSuggestionsEnabled = proactiveSuggestionsEnabled
        self.proactiveSuggestionsAvailable = proactiveSuggestionsAvailable
        self.localModels = localModels
        self.apiModels = apiModels
        self.customModels = customModels
        self.selectedModelId = selectedModelId
        self.useApiModels = useApiModels
        self.reasoningModelsAvailable = reasoningModelsAvailable
        self.localTranscriptionModels = localTranscriptionModels
        self.apiTranscriptionModels = apiTranscriptionModels
        self.selectedTranscriptionModelId = selectedTranscriptionModelId
        self.transcriptionModelsAvailable = transcriptionModelsAvailable
    }
}

enum HomeSettingsPayloadBuilder {
    static func makeFieldsPayload(_ fields: HomeSettingsFields) -> [String: Any] {
        [
            "setupAssistantPending": fields.setupAssistantPending,
            "setupAssistantStateAvailable": fields.setupAssistantStateAvailable,
            "permissionsGrantedCount": fields.permissionsGrantedCount,
            "permissionsTotalCount": fields.permissionsTotalCount,
            "enableMonitoringAtStartup": fields.enableMonitoringAtStartup,
            "enableVoiceListenerAtStartup": fields.enableVoiceListenerAtStartup,
            "startActivityCaptureAtLaunch": fields.startActivityCaptureAtLaunch,
            "startMeetingDetectionAtLaunch": fields.startMeetingDetectionAtLaunch,
            "backgroundBehaviorAvailable": fields.backgroundBehaviorAvailable,
            "activityCaptureEnabled": fields.activityCaptureEnabled,
            "activityCaptureAvailable": fields.activityCaptureAvailable,
            "meetingDetectionEnabled": fields.meetingDetectionEnabled,
            "meetingDetectionAvailable": fields.meetingDetectionAvailable,
            "proactiveSuggestionsEnabled": fields.proactiveSuggestionsEnabled,
            "proactiveSuggestionsAvailable": fields.proactiveSuggestionsAvailable,
            "localModels": fields.localModels.map(ReasoningDefaultsSettingsPayloadBuilder.makeModelInfoPayload),
            "apiModels": fields.apiModels.map(ReasoningDefaultsSettingsPayloadBuilder.makeModelInfoPayload),
            "customModels": fields.customModels.map(ReasoningDefaultsSettingsPayloadBuilder.makeModelInfoPayload),
            "selectedModelId": fields.selectedModelId,
            "useApiModels": fields.useApiModels,
            "reasoningModelsAvailable": fields.reasoningModelsAvailable,
            "localTranscriptionModels": fields.localTranscriptionModels.map(makeTranscriptionModelPayload),
            "apiTranscriptionModels": fields.apiTranscriptionModels.map(makeTranscriptionModelPayload),
            "selectedTranscriptionModelId": fields.selectedTranscriptionModelId,
            "transcriptionModelsAvailable": fields.transcriptionModelsAvailable,
        ]
    }

    private static func makeTranscriptionModelPayload(_ model: TranscriptionModelOption) -> [String: Any] {
        var payload: [String: Any] = [
            "id": model.id,
            "displayName": model.displayName,
            "isApiModel": model.isApiModel,
        ]
        if let provider = model.provider {
            payload["provider"] = provider
        }
        return payload
    }
}
