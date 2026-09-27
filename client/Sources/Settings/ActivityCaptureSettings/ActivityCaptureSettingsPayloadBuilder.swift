import AppKit

private struct ActivityCaptureAppEntry {
    let bundleId: String
    let name: String
    let iconDataUrl: String?
}

@MainActor
enum ActivityCaptureSettingsPayloadBuilder {
    private static var appIconDataUrlCache: [String: String] = [:]

    static func makeSettingsPayload(viewModel: ActivityCaptureSettingsViewModel) -> [String: Any] {
        let calendar = Calendar.current
        let cleanupComponents = calendar.dateComponents([.hour, .minute], from: viewModel.cleanupTime)
        return [
            "enabled": viewModel.automaticCaptureEnabled,
            "frequencySeconds": Int((viewModel.captureFrequencyMinutes * 60).rounded()),
            "idleThresholdSeconds": Int(viewModel.idleThresholdSeconds.rounded()),
            "postWakeGraceSeconds": Int(viewModel.postWakeGraceSeconds.rounded()),
            "excludedBundleIds": viewModel.excludedBundleIds,
            "processingModel": viewModel.selectedProcessingModel,
            "processingMode": viewModel.processingMode.rawValue,
            "scheduledProcessingTime": viewModel.getCurrentScheduledTimeString(),
            "processingMaxRecords": viewModel.processingMaxRecords,
            "autoCleanupEnabled": viewModel.autoCleanupEnabled,
            "retentionDays": viewModel.retentionDays,
            "cleanupHour": cleanupComponents.hour ?? 2,
            "cleanupMinute": cleanupComponents.minute ?? 0,
            "maxStorageMb": viewModel.maxStorageMb,
        ]
    }

    static func makeStatusPayload(viewModel: ActivityCaptureSettingsViewModel) -> [String: Any] {
        var payload: [String: Any] = [
            "isSchedulerRunning": viewModel.isSchedulerRunning,
            "todaysCaptures": viewModel.todaysCaptures,
            "totalCapturesLast7Days": viewModel.totalCapturesLast7Days,
            "totalCapturesLast30Days": viewModel.totalCapturesLast30Days,
            "pendingCaptures": viewModel.pendingCaptures,
            "failedCaptures": viewModel.failedCaptures,
            "skippedCaptureCount": viewModel.skippedCaptureCount,
            "compactedCaptureCount": viewModel.compactedCaptureCount,
        ]
        if let nextCaptureTime = viewModel.nextCaptureTime {
            payload["nextCaptureTime"] = ISO8601DateFormatter().string(from: nextCaptureTime)
        } else {
            payload["nextCaptureTime"] = NSNull()
        }
        if let lastPolicyDecision = viewModel.lastPolicyDecision {
            payload["lastPolicyDecision"] = lastPolicyDecision
        } else {
            payload["lastPolicyDecision"] = NSNull()
        }
        return payload
    }

    static func makeStatsPayload(viewModel: ActivityCaptureSettingsViewModel) -> [String: Any]? {
        guard let stats = viewModel.captureStats else { return nil }
        return [
            "totalFiles": stats.totalFiles,
            "totalSizeBytes": stats.totalSizeBytes,
            "filesLast7Days": stats.filesLast7Days,
            "filesLast30Days": stats.filesLast30Days,
        ]
    }

    static func makeProcessingProgressPayload(viewModel: ActivityCaptureSettingsViewModel) -> Any {
        guard let progress = viewModel.processingProgress else { return NSNull() }
        return [
            "active": progress.active,
            "total": progress.total,
            "processed": progress.processed,
            "succeeded": progress.succeeded,
            "failed": progress.failed,
            "remaining": progress.remaining,
            "etaSeconds": progress.etaSeconds ?? NSNull(),
            "cancelRequested": progress.cancelRequested || viewModel.isCancellingProcessing,
            "processingStrategy": progress.processingStrategy ?? NSNull(),
            "analysisConcurrency": progress.analysisConcurrency ?? NSNull(),
        ] as [String: Any]
    }

    static func makeModelsPayload(viewModel: ActivityCaptureSettingsViewModel) -> [[String: Any]] {
        viewModel.availableModels.map { model in
            [
                "id": model.id,
                "displayName": model.displayName,
                "provider": model.provider,
                "isLocal": model.isLocal,
            ]
        }
    }

    /// Lists currently running regular (GUI, Dock-visible) applications so the Exclusions
    /// picker can offer search-by-name with icons, matching the native `ExcludedAppsPicker`.
    static func makeAvailableAppsPayload() -> [[String: Any]] {
        var seenBundleIds = Set<String>()
        let entries: [ActivityCaptureAppEntry] = NSWorkspace.shared.runningApplications.compactMap { app in
            guard app.activationPolicy == .regular, let rawBundleID = app.bundleIdentifier else { return nil }
            let bundleId = AudioAppNameResolver.parentBundleID(from: rawBundleID)
            guard seenBundleIds.insert(bundleId).inserted else { return nil }
            let name = app.localizedName ?? AudioAppNameResolver.displayName(forBundleID: bundleId)
            return ActivityCaptureAppEntry(bundleId: bundleId, name: name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: app.icon))
        }
        return serializeAppEntries(entries)
    }

    /// Searches both currently running apps and apps installed under the standard Applications
    /// directories by name/bundle-id substring, so the Exclusions picker can find an app the user
    /// has not yet launched (e.g. Parallels Desktop before its first run). Unlike
    /// `makeAvailableAppsPayload`, this is only invoked once the user has typed a non-empty query;
    /// it is not meant to pre-populate the picker.
    static func makeAppSearchResultsPayload(query: String) -> [[String: Any]] {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuery.isEmpty else { return [] }
        let lowerQuery = trimmedQuery.lowercased()

        var seenBundleIds = Set<String>()
        var entries: [ActivityCaptureAppEntry] = []

        for app in NSWorkspace.shared.runningApplications {
            guard app.activationPolicy == .regular, let rawBundleID = app.bundleIdentifier else { continue }
            let bundleId = AudioAppNameResolver.parentBundleID(from: rawBundleID)
            let name = app.localizedName ?? AudioAppNameResolver.displayName(forBundleID: bundleId)
            guard name.lowercased().contains(lowerQuery) || bundleId.lowercased().contains(lowerQuery) else { continue }
            guard seenBundleIds.insert(bundleId).inserted else { continue }
            entries.append(ActivityCaptureAppEntry(bundleId: bundleId, name: name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: app.icon)))
        }

        for installedApp in scanInstalledApplications() {
            let bundleId = AudioAppNameResolver.parentBundleID(from: installedApp.bundleId)
            guard installedApp.name.lowercased().contains(lowerQuery) || bundleId.lowercased().contains(lowerQuery) else { continue }
            guard seenBundleIds.insert(bundleId).inserted else { continue }
            let icon = NSWorkspace.shared.icon(forFile: installedApp.url.path)
            entries.append(ActivityCaptureAppEntry(bundleId: bundleId, name: installedApp.name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: icon)))
        }

        let sorted = entries.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        return serializeAppEntries(Array(sorted.prefix(20)))
    }

    /// Resolves display name and icon for every currently excluded bundle ID, regardless of
    /// whether that app is running right now or was excluded in a previous session. This is what
    /// lets an already-selected exclusion chip show its real name/icon instead of the raw bundle
    /// ID on a fresh settings load.
    static func makeExcludedAppsPayload(viewModel: ActivityCaptureSettingsViewModel) -> [[String: Any]] {
        viewModel.excludedBundleIds.map { rawBundleId -> [String: Any] in
            let bundleId = AudioAppNameResolver.parentBundleID(from: rawBundleId)
            let resolvedURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId)
            let name = AudioAppNameResolver.displayName(forBundleID: bundleId, bundleURL: resolvedURL, pid: -1)
            let icon = resolvedURL.map { NSWorkspace.shared.icon(forFile: $0.path) }
            return [
                "bundleId": bundleId,
                "name": name,
                "iconDataUrl": appIconDataUrl(bundleId: bundleId, icon: icon) ?? NSNull(),
            ]
        }
    }

    private static func serializeAppEntries(_ entries: [ActivityCaptureAppEntry]) -> [[String: Any]] {
        entries
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            .map { entry in
                [
                    "bundleId": entry.bundleId,
                    "name": entry.name,
                    "iconDataUrl": entry.iconDataUrl ?? NSNull(),
                ]
            }
    }

    /// Enumerates `.app` bundles under the standard Applications directories without launching
    /// them, so not-yet-running apps (e.g. a freshly installed Parallels Desktop) are searchable.
    private static func scanInstalledApplications() -> [(bundleId: String, name: String, url: URL)] {
        let directories = [
            "/Applications",
            "/System/Applications",
            "/System/Applications/Utilities",
            NSHomeDirectory() + "/Applications",
        ].map { URL(fileURLWithPath: $0) }

        var results: [(bundleId: String, name: String, url: URL)] = []
        for directory in directories {
            guard let entries = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else { continue }
            for entry in entries where entry.pathExtension.lowercased() == "app" {
                guard let bundle = Bundle(url: entry), let bundleId = bundle.bundleIdentifier else { continue }
                let name = (bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
                    ?? (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String)
                    ?? entry.deletingPathExtension().lastPathComponent
                results.append((bundleId: bundleId, name: name, url: entry))
            }
        }
        return results
    }

    private static func appIconDataUrl(bundleId: String, icon: NSImage?) -> String? {
        if let cached = appIconDataUrlCache[bundleId] {
            return cached
        }
        guard let icon else { return nil }

        let size = NSSize(width: 24, height: 24)
        let renderedIcon = NSImage(size: size)
        renderedIcon.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .high
        icon.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .copy, fraction: 1)
        renderedIcon.unlockFocus()

        guard let tiff = renderedIcon.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            return nil
        }

        let dataUrl = "data:image/png;base64,\(png.base64EncodedString())"
        appIconDataUrlCache[bundleId] = dataUrl
        return dataUrl
    }
}
