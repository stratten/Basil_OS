import SwiftUI

@MainActor
final class PermissionsSettingsViewModel: ObservableObject {
    @Published var approvalSettings: ExecutionApprovalSettings?
    @Published var whitelistPatterns: [WhitelistPattern] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    func loadApprovalData() async {
        #if DEBUG
        DevLogger.shared.info("🔄 loadApprovalData() started", context: "PermissionsSettingsViewModel")
        #endif
        
        // Ensure we're on MainActor
        await MainActor.run {
            #if DEBUG
            DevLogger.shared.info("🔄 Inside MainActor.run - setting isLoading", context: "PermissionsSettingsViewModel")
            #endif
            self.isLoading = true
            self.errorMessage = nil
        }

        #if DEBUG
        DevLogger.shared.info("🔄 About to enter do block", context: "PermissionsSettingsViewModel")
        #endif
        
        do {
            #if DEBUG
            DevLogger.shared.info("📡 Step 1: Fetching settings...", context: "PermissionsSettingsViewModel")
            #endif
            let settings = try await fetchSettings()
            
            #if DEBUG
            DevLogger.shared.info("📡 Step 2: Fetching whitelist patterns...", context: "PermissionsSettingsViewModel")
            #endif
            let patterns = try await fetchWhitelistPatterns()

            #if DEBUG
            DevLogger.shared.info("📡 Step 3: Updating UI with \(patterns.count) patterns", context: "PermissionsSettingsViewModel")
            #endif
            
            await MainActor.run {
                updateApprovalSettings(settings, whitelistCount: patterns.count)
                whitelistPatterns = patterns
                isLoading = false
            }

            #if DEBUG
            DevLogger.shared.info("✅ Approval data ready (mode=\(approvalSettings?.approvalMode ?? .whitelistOnly), whitelist=\(patterns.count))", context: "PermissionsSettingsViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ loadApprovalData() failed at some step: \(error)", context: "PermissionsSettingsViewModel")
            #endif
            await MainActor.run {
                handleLoadFailure(error)
            }
        }
    }

    private func fetchSettings() async throws -> ExecutionApprovalSettings {
        #if DEBUG
        DevLogger.shared.info("📥 [FETCH_SETTINGS] Starting API call", context: "PermissionsSettingsViewModel")
        #endif
        do {
            #if DEBUG
            DevLogger.shared.info("📥 [FETCH_SETTINGS] About to call apiClient.getApprovalSettings()", context: "PermissionsSettingsViewModel")
            #endif
            let settings = try await apiClient.getApprovalSettings()
            #if DEBUG
            DevLogger.shared.info("📥 [FETCH_SETTINGS] SUCCESS - Received approval settings (mode=\(settings.approvalMode))", context: "PermissionsSettingsViewModel")
            #endif
            return settings
        } catch {
            #if DEBUG
            DevLogger.shared.error("⚠️ [FETCH_SETTINGS] FAILED: \(error)", context: "PermissionsSettingsViewModel")
            #endif
            throw error
        }
    }

    private func fetchWhitelistPatterns() async throws -> [WhitelistPattern] {
        #if DEBUG
        DevLogger.shared.info("📥 [FETCH_WHITELIST] Starting fetch", context: "PermissionsSettingsViewModel")
        #endif
        do {
            #if DEBUG
            DevLogger.shared.info("📥 [FETCH_WHITELIST] About to call apiClient.getWhitelistPatterns()", context: "PermissionsSettingsViewModel")
            #endif
            let response = try await apiClient.getWhitelistPatterns()
            #if DEBUG
            DevLogger.shared.info("📥 [FETCH_WHITELIST] SUCCESS - Received whitelist response (count=\(response.totalCount), patterns=\(response.patterns.count))", context: "PermissionsSettingsViewModel")
            #endif
            return response.patterns
        } catch {
            #if DEBUG
            DevLogger.shared.error("⚠️ [FETCH_WHITELIST] FAILED: \(error)", context: "PermissionsSettingsViewModel")
            #endif
            throw error
        }
    }

    private func handleLoadFailure(_ error: Error) {
        #if DEBUG
        DevLogger.shared.error("❌ Failed to load approval data: \(error)", context: "PermissionsSettingsViewModel")
        #endif

        approvalSettings = nil
        whitelistPatterns = []
        errorMessage = "Failed to load command approval settings: \(error.localizedDescription)"
        isLoading = false
    }

    func updateApprovalMode(_ newMode: ExecutionApprovalSettings.ApprovalMode) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(approvalMode: newMode.rawValue))
    }

    func updateAutoApproveReadOnly(_ newValue: Bool) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(autoApproveReadOnly: newValue))
    }

    func updateBlockDangerousPatterns(_ newValue: Bool) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(blockDangerousPatterns: newValue))
    }

    func updateSafeExecutionMode(_ newValue: Bool) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(safeExecutionMode: newValue))
    }

    func updateApprovalSettings(_ request: UpdateApprovalSettingsRequest) async {
        errorMessage = nil
        do {
            let updatedSettings = try await apiClient.updateApprovalSettings(request)
            approvalSettings = updatedSettings
        } catch {
            errorMessage = "Failed to update command approval settings: \(error.localizedDescription)"
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update command approval settings: \(error)", context: "PermissionsSettingsViewModel")
            #endif
        }
    }

    func updateApprovalTimeoutSeconds(_ newValue: Int) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(approvalTimeoutSeconds: newValue))
    }

    func updateTimeoutBehavior(_ newBehavior: ExecutionApprovalSettings.TimeoutBehavior) async {
        await updateApprovalSettings(UpdateApprovalSettingsRequest(timeoutBehavior: newBehavior.rawValue))
    }

    func addWhitelistPattern(pattern: String, patternType: String, description: String) async {
        errorMessage = nil
        #if DEBUG
        DevLogger.shared.info("🔄 Adding whitelist pattern '\(pattern)'", context: "PermissionsSettingsViewModel")
        #endif
        do {
            let request = AddWhitelistRequest(
                pattern: pattern,
                patternType: patternType,
                description: description,
                riskLevel: "low"
            )

            let newPattern = try await apiClient.addWhitelistPattern(request)
            whitelistPatterns.append(newPattern)

            #if DEBUG
            DevLogger.shared.info("✅ Added whitelist pattern: \(pattern)", context: "PermissionsSettingsViewModel")
            #endif

            await refreshWhitelist()
        } catch {
            errorMessage = "Failed to add whitelist pattern: \(error.localizedDescription)"
            #if DEBUG
            DevLogger.shared.error("❌ Failed to add whitelist pattern: \(error)", context: "PermissionsSettingsViewModel")
            #endif
        }
    }

    func updateWhitelistPattern(id: String, pattern: String, patternType: String, description: String) async {
        errorMessage = nil
        #if DEBUG
        DevLogger.shared.info("🔄 Updating whitelist pattern \(id) to '\(pattern)'", context: "PermissionsSettingsViewModel")
        #endif
        do {
            let request = UpdateWhitelistRequest(
                pattern: pattern,
                patternType: patternType,
                description: description
            )

            let updatedPattern = try await apiClient.updateWhitelistPattern(id: id, request: request)
            
            // Update local array
            if let index = whitelistPatterns.firstIndex(where: { $0.id == id }) {
                whitelistPatterns[index] = updatedPattern
            }

            #if DEBUG
            DevLogger.shared.info("✅ Updated whitelist pattern: \(id)", context: "PermissionsSettingsViewModel")
            #endif

            await refreshWhitelist()
        } catch {
            errorMessage = "Failed to update whitelist pattern: \(error.localizedDescription)"
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update whitelist pattern: \(error)", context: "PermissionsSettingsViewModel")
            #endif
        }
    }

    func removeWhitelistPattern(id: String) async {
        errorMessage = nil
        #if DEBUG
        DevLogger.shared.info("🔄 Removing whitelist pattern \(id)", context: "PermissionsSettingsViewModel")
        #endif
        do {
            try await apiClient.removeWhitelistPattern(id: id)
            whitelistPatterns.removeAll { $0.id == id }

            #if DEBUG
            DevLogger.shared.info("✅ Removed whitelist pattern: \(id)", context: "PermissionsSettingsViewModel")
            #endif

            await refreshWhitelist()
        } catch {
            errorMessage = "Failed to remove whitelist pattern: \(error.localizedDescription)"
            #if DEBUG
            DevLogger.shared.error("❌ Failed to remove whitelist pattern: \(error)", context: "PermissionsSettingsViewModel")
            #endif
        }
    }

    private func refreshWhitelist() async {
        do {
            let patternsResponse = try await apiClient.getWhitelistPatterns()
            whitelistPatterns = patternsResponse.patterns
            if let settings = approvalSettings {
                updateApprovalSettings(settings, whitelistCount: patternsResponse.totalCount)
            }
            #if DEBUG
            DevLogger.shared.info("📥 Refreshed whitelist (count=\(patternsResponse.totalCount))", context: "PermissionsSettingsViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to refresh whitelist patterns: \(error)", context: "PermissionsSettingsViewModel")
            #endif
        }
    }

    private func updateApprovalSettings(_ settings: ExecutionApprovalSettings, whitelistCount: Int) {
        approvalSettings = ExecutionApprovalSettings(
            approvalMode: settings.approvalMode,
            showFullCommandInPrompt: settings.showFullCommandInPrompt,
            rememberChoiceOption: settings.rememberChoiceOption,
            autoApproveReadOnly: settings.autoApproveReadOnly,
            blockDangerousPatterns: settings.blockDangerousPatterns,
            whitelistedCount: whitelistCount,
            safeExecutionMode: settings.safeExecutionMode,
            approvalTimeoutSeconds: settings.approvalTimeoutSeconds,
            timeoutBehavior: settings.timeoutBehavior
        )
    }
}

