import Foundation

enum SkillsSettingsPayloadBuilder {
    static func makeSnapshotPayload(
        skillCandidates: [SkillCandidateDTO],
        savedSkills: [SkillDTO],
        reconciliationActive: Bool,
        skillAfterTaskEnabled: Bool,
        skillDailyEnabled: Bool,
        skillDailyTimeLocal: String,
        skillProcessingModel: String?,
        skillReconciliationMinInstances: Int,
        availableSkillProcessingModels: [ReasoningModelInfo],
        pendingCandidateActionIDs: Set<String>,
        pendingSkillDeletionSlugs: Set<String>,
        isLoadingSkillsState: Bool,
        isRunningSkillsIntelligence: Bool,
        skillsStatusMessage: String?
    ) -> [String: Any] {
        [
            "skillCandidates": skillCandidates.map(makeCandidatePayload),
            "savedSkills": savedSkills.map(makeSkillPayload),
            "reconciliationActive": reconciliationActive,
            "skillAfterTaskEnabled": skillAfterTaskEnabled,
            "skillDailyEnabled": skillDailyEnabled,
            "skillDailyTimeLocal": skillDailyTimeLocal,
            "skillProcessingModel": (skillProcessingModel ?? NSNull()) as Any,
            "skillReconciliationMinInstances": skillReconciliationMinInstances,
            "availableSkillProcessingModels": availableSkillProcessingModels.map(makeModelInfoPayload),
            "pendingCandidateActionIDs": Array(pendingCandidateActionIDs),
            "pendingSkillDeletionSlugs": Array(pendingSkillDeletionSlugs),
            "isLoadingSkillsState": isLoadingSkillsState,
            "isRunningSkillsIntelligence": isRunningSkillsIntelligence,
            "statusMessage": (skillsStatusMessage ?? NSNull()) as Any,
        ]
    }

    @MainActor
    static func makeSnapshotPayload(viewModel: ReasoningSettingsViewModel) -> [String: Any] {
        makeSnapshotPayload(
            skillCandidates: viewModel.skillCandidates,
            savedSkills: viewModel.savedSkills,
            reconciliationActive: viewModel.reconciliationActive,
            skillAfterTaskEnabled: viewModel.skillAfterTaskEnabled,
            skillDailyEnabled: viewModel.skillDailyEnabled,
            skillDailyTimeLocal: viewModel.skillDailyTimeLocal,
            skillProcessingModel: viewModel.skillProcessingModel,
            skillReconciliationMinInstances: viewModel.skillReconciliationMinInstances,
            availableSkillProcessingModels: viewModel.availableSkillProcessingModels,
            pendingCandidateActionIDs: viewModel.pendingCandidateActionIDs,
            pendingSkillDeletionSlugs: viewModel.pendingSkillDeletionSlugs,
            isLoadingSkillsState: viewModel.isLoadingSkillsState,
            isRunningSkillsIntelligence: viewModel.isRunningSkillsIntelligence,
            skillsStatusMessage: viewModel.skillsStatusMessage
        )
    }

    static func makeCandidatePayload(_ candidate: SkillCandidateDTO) -> [String: Any] {
        [
            "id": candidate.id,
            "title": candidate.title,
            "whenToUse": candidate.whenToUse,
            "createdAt": candidate.createdAt,
            "observationCount": candidate.observationCount,
        ]
    }

    static func makeSkillPayload(_ skill: SkillDTO) -> [String: Any] {
        [
            "slug": skill.slug,
            "title": skill.title,
            "whenToUse": skill.whenToUse,
            "version": skill.version,
            "observationCount": skill.observationCount,
            "lastUsed": (skill.lastUsed ?? NSNull()) as Any,
            "sizeBytes": skill.sizeBytes,
            "capBytes": skill.capBytes,
        ]
    }

    static func makeModelInfoPayload(_ model: ReasoningModelInfo) -> [String: Any] {
        ["id": model.id, "displayName": model.displayName]
    }
}
