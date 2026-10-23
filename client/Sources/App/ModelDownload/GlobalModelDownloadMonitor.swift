import AppKit
import Foundation

struct ModelDownloadActivityEntry: Decodable, Equatable, Identifiable {
    var id: String { modelId }

    let modelId: String
    let modelType: String
    let variant: String
    let progress: Double
    let status: String
    let totalDownloaded: Int64
    let totalSize: Int64
    let message: String
    let currentFile: String
    let currentFilePercent: Double
    let filesCompleted: Int
    let totalFiles: Int
}

private struct ModelDownloadActivityResponse: Decodable {
    let downloads: [ModelDownloadActivityEntry]
}

@MainActor
final class GlobalModelDownloadMonitor {
    static let shared = GlobalModelDownloadMonitor()

    private static let activeStatuses: Set<String> = ["queued", "downloading"]
    private static let pollingIntervalNanoseconds: UInt64 = 2_000_000_000
    private static let terminalGracePeriod: TimeInterval = 4

    private var pollingTask: Task<Void, Never>?
    private var terminalStatusObservedAt: [String: Date] = [:]

    private init() {}

    func start() {
        guard pollingTask == nil else { return }

        pollingTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.pollDownloadActivity()
                try? await Task.sleep(nanoseconds: Self.pollingIntervalNanoseconds)
            }
        }
    }

    func stop() {
        pollingTask?.cancel()
        pollingTask = nil
        terminalStatusObservedAt.removeAll()
    }

    private func pollDownloadActivity() async {
        let response: ModelDownloadActivityResponse
        do {
            response = try await APIClient.shared.get(
                "/models/download/active",
                decoding: ModelDownloadActivityResponse.self
            )
        } catch {
            return
        }

        let now = Date()
        var displayedEntries: [ModelDownloadActivityEntry] = []
        let fetchedIds = Set(response.downloads.map(\.modelId))

        for entry in response.downloads {
            if Self.activeStatuses.contains(entry.status) {
                terminalStatusObservedAt[entry.modelId] = nil
                displayedEntries.append(entry)
                continue
            }

            let observedAt = terminalStatusObservedAt[entry.modelId] ?? now
            terminalStatusObservedAt[entry.modelId] = observedAt
            if now.timeIntervalSince(observedAt) < Self.terminalGracePeriod {
                displayedEntries.append(entry)
            }
        }

        let staleIds = terminalStatusObservedAt.keys.filter { !fetchedIds.contains($0) }
        for modelId in staleIds {
            terminalStatusObservedAt.removeValue(forKey: modelId)
        }

        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
        if displayedEntries.isEmpty {
            appDelegate.hideModelDownloadWidgetIfNeeded()
            return
        }

        appDelegate.showModelDownloadWidget()
        appDelegate.modelDownloadWindowController?.apply(entries: displayedEntries)
    }
}
