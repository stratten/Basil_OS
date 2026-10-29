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
    /// Poll quickly only while a download is visible; the backend wakes the monitor when a new one is enqueued.
    private static let activePollingIntervalNanoseconds: UInt64 = 2_000_000_000
    /// Safety net for downloads the wake event could not announce, such as a missed WebSocket message.
    private static let idlePollingIntervalNanoseconds: UInt64 = 30_000_000_000
    /// Retry cadence while the backend is not reachable yet.
    private static let unavailablePollingIntervalNanoseconds: UInt64 = 5_000_000_000
    private static let terminalGracePeriod: TimeInterval = 4

    private enum PollOutcome {
        case active
        case idle
        case unavailable
    }

    private var pollingTask: Task<Void, Never>?
    private var sleepTask: Task<Void, Never>?
    /// Set when a wake arrives while a poll is in flight, so the next wait is skipped instead of lost.
    private var wakeRequested = false
    private var terminalStatusObservedAt: [String: Date] = [:]

    private init() {}

    func start() {
        guard pollingTask == nil else { return }

        pollingTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                let outcome = await self.pollDownloadActivity()
                await self.sleepUntilNextPoll(after: outcome)
            }
        }
    }

    /// Ends the current wait so the next poll runs immediately. Called when the backend announces a new download.
    func wake() {
        wakeRequested = true
        sleepTask?.cancel()
    }

    private func sleepUntilNextPoll(after outcome: PollOutcome) async {
        if wakeRequested {
            wakeRequested = false
            return
        }
        let nanoseconds: UInt64
        switch outcome {
        case .active:
            nanoseconds = Self.activePollingIntervalNanoseconds
        case .idle:
            nanoseconds = Self.idlePollingIntervalNanoseconds
        case .unavailable:
            nanoseconds = Self.unavailablePollingIntervalNanoseconds
        }
        let task = Task<Void, Never> { _ = try? await Task.sleep(nanoseconds: nanoseconds) }
        sleepTask = task
        await task.value
        sleepTask = nil
        wakeRequested = false
    }

    func stop() {
        pollingTask?.cancel()
        pollingTask = nil
        sleepTask?.cancel()
        sleepTask = nil
        terminalStatusObservedAt.removeAll()
    }

    private func pollDownloadActivity() async -> PollOutcome {
        let response: ModelDownloadActivityResponse
        do {
            response = try await APIClient.shared.get(
                "/models/download/active",
                decoding: ModelDownloadActivityResponse.self,
                quiet: true
            )
        } catch {
            return .unavailable
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

        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else {
            return displayedEntries.isEmpty ? .idle : .active
        }
        if displayedEntries.isEmpty {
            appDelegate.hideModelDownloadWidgetIfNeeded()
            return .idle
        }

        appDelegate.showModelDownloadWidget()
        appDelegate.modelDownloadWindowController?.apply(entries: displayedEntries)
        return .active
    }
}
