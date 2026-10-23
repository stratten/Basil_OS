import Foundation
import SwiftUI

/// State and local registry mutations for the Connections Provider Profiles sub-tab.
@MainActor
final class ProviderProfilesViewModel: ObservableObject {

    @Published var profiles: [APIClient.ProviderProfileSummary] = []
    @Published var isLoading: Bool = false
    @Published var isMutating: Bool = false
    @Published var errorMessage: String?
    @Published var statusMessage: String?

    private let apiClient = APIClient.shared

    init() {
        Task { await self.loadProfiles() }
    }

    func loadProfiles() async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.profiles = try await apiClient.listProviderProfiles()
            self.errorMessage = nil
        } catch {
            self.errorMessage = "Failed to load provider profiles: \(error.localizedDescription)"
        }
    }

    func loadProfileConfiguration(
        for profile: APIClient.ProviderProfileSummary
    ) async -> APIClient.ProviderProfileConfiguration? {
        errorMessage = nil
        do {
            return try await apiClient.getProviderProfileConfiguration(profileId: profile.id)
        } catch {
            errorMessage = "Could not load \(profile.displayName): \(error.localizedDescription)"
            return nil
        }
    }

    @discardableResult
    func createProfile(
        configuration: APIClient.ProviderProfileConfigurationRequest
    ) async -> Bool {
        await performProfileMutation(
            successMessage: "Provider profile added and left disabled."
        ) {
            try await self.apiClient.createProviderProfile(configuration: configuration)
        }
    }

    @discardableResult
    func updateProfile(
        profile: APIClient.ProviderProfileSummary,
        configuration: APIClient.ProviderProfileConfigurationRequest
    ) async -> Bool {
        await performProfileMutation(
            successMessage: "Updated \(profile.displayName)."
        ) {
            try await self.apiClient.updateProviderProfile(
                profileId: profile.id,
                expectedRevision: profile.revision,
                configuration: configuration
            )
        }
    }

    @discardableResult
    func setProfileEnabled(
        _ profile: APIClient.ProviderProfileSummary,
        enabled: Bool
    ) async -> Bool {
        await performProfileMutation(
            successMessage: enabled
                ? "\(profile.displayName) is enabled."
                : "\(profile.displayName) is disabled."
        ) {
            try await self.apiClient.setProviderProfileStatus(
                profileId: profile.id,
                expectedRevision: profile.revision,
                enabled: enabled
            )
        }
    }

    @discardableResult
    func removeProfile(_ profile: APIClient.ProviderProfileSummary) async -> Bool {
        isMutating = true
        errorMessage = nil
        statusMessage = nil
        defer { isMutating = false }
        do {
            try await apiClient.removeProviderProfile(
                profileId: profile.id,
                expectedRevision: profile.revision
            )
            await loadProfiles()
            statusMessage = "Removed \(profile.displayName). Historical runs remain preserved."
            return true
        } catch {
            errorMessage = "Could not remove \(profile.displayName): \(error.localizedDescription)"
            await loadProfiles()
            return false
        }
    }

    @discardableResult
    func createWorkspaceGrant(
        for profile: APIClient.ProviderProfileSummary,
        canonicalWorkspaceRoot: String,
        workspaceLabel: String,
        description: String?,
        routingHints: [String]
    ) async -> Bool {
        await performInventoryMutation(
            successMessage: "Authorized \(workspaceLabel) for \(profile.displayName)."
        ) {
            _ = try await self.apiClient.createWorkspaceGrant(
                profileId: profile.id,
                canonicalWorkspaceRoot: canonicalWorkspaceRoot,
                workspaceLabel: workspaceLabel,
                description: description,
                routingHints: routingHints
            )
        }
    }

    @discardableResult
    func updateWorkspaceGrant(
        profile: APIClient.ProviderProfileSummary,
        grant: APIClient.ProviderProfileWorkspaceGrantSummary,
        workspaceLabel: String,
        description: String?,
        routingHints: [String]
    ) async -> Bool {
        await performInventoryMutation(
            successMessage: "Updated \(grant.workspaceLabel)."
        ) {
            _ = try await self.apiClient.updateWorkspaceGrant(
                profileId: profile.id,
                grantId: grant.id,
                expectedRevision: grant.revision,
                workspaceLabel: workspaceLabel,
                description: description,
                routingHints: routingHints
            )
        }
    }

    @discardableResult
    func revokeWorkspaceGrant(
        profile: APIClient.ProviderProfileSummary,
        grant: APIClient.ProviderProfileWorkspaceGrantSummary
    ) async -> Bool {
        await performInventoryMutation(
            successMessage: "Revoked \(grant.workspaceLabel). No local files were deleted."
        ) {
            try await self.apiClient.revokeWorkspaceGrant(
                profileId: profile.id,
                grantId: grant.id,
                expectedRevision: grant.revision
            )
        }
    }

    private func performProfileMutation(
        successMessage: String,
        operation: () async throws -> APIClient.ProviderProfileConfiguration
    ) async -> Bool {
        isMutating = true
        errorMessage = nil
        statusMessage = nil
        defer { isMutating = false }
        do {
            let updated = try await operation()
            replaceProfile(updated)
            statusMessage = successMessage
            return true
        } catch {
            errorMessage = "Provider profile update failed: \(error.localizedDescription)"
            await loadProfiles()
            return false
        }
    }

    private func performInventoryMutation(
        successMessage: String,
        operation: () async throws -> Void
    ) async -> Bool {
        isMutating = true
        errorMessage = nil
        statusMessage = nil
        defer { isMutating = false }
        do {
            try await operation()
            await loadProfiles()
            statusMessage = successMessage
            return true
        } catch {
            errorMessage = "Workspace authorization update failed: \(error.localizedDescription)"
            await loadProfiles()
            return false
        }
    }

    private func replaceProfile(_ configuration: APIClient.ProviderProfileConfiguration) {
        let profile = APIClient.ProviderProfileSummary(
            id: configuration.id,
            displayName: configuration.displayName,
            status: configuration.status,
            capabilityState: configuration.capabilityState,
            description: configuration.description,
            routingHints: configuration.routingHints,
            revision: configuration.revision,
            hasObservedCapabilities: configuration.hasObservedCapabilities,
            activeWorkspaceGrants: configuration.activeWorkspaceGrants,
            isStructurallyValid: configuration.isStructurallyValid,
            validationError: configuration.validationError,
            createdAt: configuration.createdAt,
            updatedAt: configuration.updatedAt
        )
        if let index = profiles.firstIndex(where: { $0.id == profile.id }) {
            profiles[index] = profile
        } else {
            profiles.append(profile)
        }
    }
}
