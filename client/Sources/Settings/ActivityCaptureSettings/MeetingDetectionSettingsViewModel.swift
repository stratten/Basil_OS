import Foundation
import AppKit
import SwiftUI

@MainActor
final class MeetingDetectionSettingsViewModel: ObservableObject {
    @Published var enabled = false
    @Published var mode = "prompt"
    @Published var pollSeconds = 10.0
    @Published var excludedBundleIds: [String] = []
    @Published var selectedExclusionBundleId: String?
    @Published var excludedAppNamesText = ""
    @Published var cooldownMinutes = 10.0
    @Published var useCalendarEnrichment = false
    @Published var requireCalendarMatch = false
    @Published var autoEnd = false
    @Published var inactivityTimeoutMinutes = 2.0
    @Published var isLoading = false
    @Published var isSaving = false
    @Published var statusMessage: String?

    private let apiClient = APIClient.shared
    private var loadedSettings: MeetingDetectionSettingsData?
    private var isApplyingRemoteSettings = false
    private let logContext = "MeetingDetectionSettings"

    var excludedAppNames: [String] {
        excludedAppNamesText
            .split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    func load() async {
        DevLogger.shared.info("Loading Meeting/Call Detection settings", context: logContext)
        isLoading = true
        defer { isLoading = false }

        do {
            let settings = try await apiClient.getMeetingDetectionSettings()
            apply(settings)
            DevLogger.shared.info(
                "Loaded Meeting/Call Detection settings: enabled=\(settings.enabled), mode=\(settings.mode), poll=\(settings.pollSeconds)",
                context: logContext
            )
        } catch {
            statusMessage = "Error loading Meeting/Call Detection settings: \(error.localizedDescription)"
            DevLogger.shared.error(statusMessage ?? "", context: logContext)
        }
    }

    func updateEnabled(_ isEnabled: Bool) async {
        let previousValue = loadedSettings?.enabled ?? !isEnabled
        await update(
            MeetingDetectionSettingsUpdate(enabled: isEnabled),
            successMessage: isEnabled ? "Meeting/Call Detection enabled." : "Meeting/Call Detection disabled.",
            failureMessage: "Error updating Meeting/Call Detection enabled state"
        ) {
            self.enabled = previousValue
        }
    }

    func updateMode(_ mode: String) async {
        await update(
            MeetingDetectionSettingsUpdate(mode: mode),
            successMessage: "Meeting/Call Detection mode updated.",
            failureMessage: "Error updating Meeting/Call Detection mode"
        )
    }

    func updatePollSeconds(_ seconds: Double) async {
        let clamped = min(max(seconds, 1.0), 600.0)
        pollSeconds = clamped
        await update(
            MeetingDetectionSettingsUpdate(pollSeconds: clamped),
            successMessage: "Meeting/Call Detection poll interval updated.",
            failureMessage: "Error updating Meeting/Call Detection poll interval"
        )
    }

    func updateCooldownMinutes(_ minutes: Double) async {
        await update(
            MeetingDetectionSettingsUpdate(cooldownMinutes: minutes),
            successMessage: "Meeting/Call Detection cooldown updated.",
            failureMessage: "Error updating Meeting/Call Detection cooldown"
        )
    }

    func addExcludedBundleId(_ bundleID: String) async {
        let normalized = AudioAppNameResolver.parentBundleID(from: bundleID)
        guard !normalized.isEmpty, !excludedBundleIds.contains(normalized) else { return }
        await updateExcludedBundleIds(excludedBundleIds + [normalized])
        selectedExclusionBundleId = nil
    }

    func removeExcludedBundleId(_ bundleID: String) async {
        let normalized = AudioAppNameResolver.parentBundleID(from: bundleID)
        await updateExcludedBundleIds(excludedBundleIds.filter { $0 != normalized })
    }

    func updateExcludedBundleIds(_ bundleIDs: [String]) async {
        let normalized = uniquePreservingOrder(
            bundleIDs
                .map { AudioAppNameResolver.parentBundleID(from: $0.trimmingCharacters(in: .whitespacesAndNewlines)) }
                .filter { !$0.isEmpty }
        )
        await update(
            MeetingDetectionSettingsUpdate(excludedBundleIds: normalized),
            successMessage: "Excluded bundle IDs updated.",
            failureMessage: "Error updating excluded bundle IDs"
        )
    }

    func updateExcludedAppNames() async {
        await update(
            MeetingDetectionSettingsUpdate(excludedAppNames: excludedAppNames),
            successMessage: "Meeting/Call Detection exclusions updated.",
            failureMessage: "Error updating Meeting/Call Detection exclusions"
        )
    }

    func updateUseCalendarEnrichment(_ value: Bool) async {
        if value {
            await MeetingDetectionCalendarAccess.requestIfNeeded()
        }
        await update(
            MeetingDetectionSettingsUpdate(useCalendarEnrichment: value),
            successMessage: "Calendar enrichment updated.",
            failureMessage: "Error updating calendar enrichment"
        )
    }

    func updateRequireCalendarMatch(_ value: Bool) async {
        if value {
            await MeetingDetectionCalendarAccess.requestIfNeeded()
        }
        await update(
            MeetingDetectionSettingsUpdate(requireCalendarMatch: value),
            successMessage: "Calendar match requirement updated.",
            failureMessage: "Error updating calendar match requirement"
        )
    }

    func updateAutoEnd(_ value: Bool) async {
        await update(
            MeetingDetectionSettingsUpdate(autoEnd: value),
            successMessage: "Auto-end updated.",
            failureMessage: "Error updating auto-end"
        )
    }

    func updateInactivityTimeout(_ minutes: Double) async {
        let clamped = min(max(minutes, 0.0), 600.0)
        inactivityTimeoutMinutes = clamped
        await update(
            MeetingDetectionSettingsUpdate(inactivityTimeoutMinutes: clamped),
            successMessage: "Inactivity timeout updated.",
            failureMessage: "Error updating inactivity timeout"
        )
    }

    private func apply(_ settings: MeetingDetectionSettingsData) {
        isApplyingRemoteSettings = true
        defer { isApplyingRemoteSettings = false }
        loadedSettings = settings
        enabled = settings.enabled
        mode = settings.mode
        pollSeconds = settings.pollSeconds
        excludedBundleIds = uniquePreservingOrder(settings.excludedBundleIds.map { AudioAppNameResolver.parentBundleID(from: $0) })
        excludedAppNamesText = settings.excludedAppNames.joined(separator: "\n")
        cooldownMinutes = settings.cooldownMinutes
        useCalendarEnrichment = settings.useCalendarEnrichment
        requireCalendarMatch = settings.requireCalendarMatch
        autoEnd = settings.autoEnd
        inactivityTimeoutMinutes = settings.inactivityTimeoutMinutes
    }

    private func update(
        _ update: MeetingDetectionSettingsUpdate,
        successMessage: String,
        failureMessage: String,
        revert: (() -> Void)? = nil
    ) async {
        guard !isLoading, !isApplyingRemoteSettings else { return }

        isSaving = true
        defer { isSaving = false }

        do {
            let settings = try await apiClient.updateMeetingDetectionSettings(update)
            apply(settings)
            statusMessage = successMessage
            DevLogger.shared.info(successMessage, context: logContext)
            NotificationCenter.default.post(name: .meetingDetectionSettingsChanged, object: nil)
            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                await appDelegate.statusBarManager?.refreshMeetingDetectionState()
            }
        } catch {
            if let revert {
                isApplyingRemoteSettings = true
                revert()
                isApplyingRemoteSettings = false
            } else if let loadedSettings {
                apply(loadedSettings)
            }
            statusMessage = "\(failureMessage): \(error.localizedDescription)"
            DevLogger.shared.error(statusMessage ?? failureMessage, context: logContext)
        }
    }

    private func uniquePreservingOrder(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.filter { seen.insert($0).inserted }
    }
}

extension Notification.Name {
    static let meetingDetectionSettingsChanged = Notification.Name("MeetingDetectionSettingsChanged")
}
