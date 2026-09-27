import AppKit

private struct MeetingDetectionAppEntry {
    let bundleId: String
    let name: String
    let iconDataUrl: String?
}

@MainActor
enum MeetingDetectionSettingsPayloadBuilder {
    private static var appIconDataUrlCache: [String: String] = [:]

    /// The bundle ID(s) the Excluded Apps picker must always treat as non-removable, mirroring
    /// `MeetingDetectionExcludedAppsPicker`'s `requiredBundleIDs` (Basil's own bundle ID, normalized
    /// through `AudioAppNameResolver.parentBundleID`, with the same literal fallback).
    static var requiredBundleIds: [String] {
        [Bundle.main.bundleIdentifier.map { AudioAppNameResolver.parentBundleID(from: $0) } ?? "com.stratten.basil"]
    }

    static func makeSettingsPayload(viewModel: MeetingDetectionSettingsViewModel) -> [String: Any] {
        [
            "enabled": viewModel.enabled,
            "mode": viewModel.mode,
            "pollSeconds": viewModel.pollSeconds,
            "excludedBundleIds": viewModel.excludedBundleIds,
            "excludedAppNames": viewModel.excludedAppNames,
            "cooldownMinutes": viewModel.cooldownMinutes,
            "useCalendarEnrichment": viewModel.useCalendarEnrichment,
            "requireCalendarMatch": viewModel.requireCalendarMatch,
            "autoEnd": viewModel.autoEnd,
            "inactivityTimeoutMinutes": viewModel.inactivityTimeoutMinutes,
        ]
    }

    /// Lists currently running regular (GUI, Dock-visible) applications so the Excluded Apps
    /// picker can offer search-by-name with icons. Mirrors
    /// `ActivityCaptureSettingsPayloadBuilder.makeAvailableAppsPayload()`.
    static func makeAvailableAppsPayload() -> [[String: Any]] {
        var seenBundleIds = Set<String>()
        let entries: [MeetingDetectionAppEntry] = NSWorkspace.shared.runningApplications.compactMap { app in
            guard app.activationPolicy == .regular, let rawBundleID = app.bundleIdentifier else { return nil }
            let bundleId = AudioAppNameResolver.parentBundleID(from: rawBundleID)
            guard seenBundleIds.insert(bundleId).inserted else { return nil }
            let name = app.localizedName ?? AudioAppNameResolver.displayName(forBundleID: bundleId)
            return MeetingDetectionAppEntry(bundleId: bundleId, name: name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: app.icon))
        }
        return serializeAppEntries(entries)
    }

    /// Searches running apps and apps installed under the standard Applications directories by
    /// name/bundle-id substring. Only invoked once the user has typed a non-empty query. Mirrors
    /// `ActivityCaptureSettingsPayloadBuilder.makeAppSearchResultsPayload(query:)`.
    static func makeAppSearchResultsPayload(query: String) -> [[String: Any]] {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuery.isEmpty else { return [] }
        let lowerQuery = trimmedQuery.lowercased()

        var seenBundleIds = Set<String>()
        var entries: [MeetingDetectionAppEntry] = []

        for app in NSWorkspace.shared.runningApplications {
            guard app.activationPolicy == .regular, let rawBundleID = app.bundleIdentifier else { continue }
            let bundleId = AudioAppNameResolver.parentBundleID(from: rawBundleID)
            let name = app.localizedName ?? AudioAppNameResolver.displayName(forBundleID: bundleId)
            guard name.lowercased().contains(lowerQuery) || bundleId.lowercased().contains(lowerQuery) else { continue }
            guard seenBundleIds.insert(bundleId).inserted else { continue }
            entries.append(MeetingDetectionAppEntry(bundleId: bundleId, name: name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: app.icon)))
        }

        for installedApp in scanInstalledApplications() {
            let bundleId = AudioAppNameResolver.parentBundleID(from: installedApp.bundleId)
            guard installedApp.name.lowercased().contains(lowerQuery) || bundleId.lowercased().contains(lowerQuery) else { continue }
            guard seenBundleIds.insert(bundleId).inserted else { continue }
            let icon = NSWorkspace.shared.icon(forFile: installedApp.url.path)
            entries.append(MeetingDetectionAppEntry(bundleId: bundleId, name: installedApp.name, iconDataUrl: appIconDataUrl(bundleId: bundleId, icon: icon)))
        }

        let sorted = entries.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        return serializeAppEntries(Array(sorted.prefix(20)))
    }

    /// Resolves display name and icon for every currently excluded bundle ID, regardless of
    /// whether that app is running right now. Mirrors
    /// `ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel:)`.
    static func makeExcludedAppsPayload(viewModel: MeetingDetectionSettingsViewModel) -> [[String: Any]] {
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

    private static func serializeAppEntries(_ entries: [MeetingDetectionAppEntry]) -> [[String: Any]] {
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
