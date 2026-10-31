import SwiftUI
import AudioToolbox
import OSLog
import Combine

struct AudioProcess: Identifiable, Hashable, Sendable {
    enum Kind: String, Sendable {
        case process
        case app
    }
    var id: pid_t
    var kind: Kind
    var name: String
    var audioActive: Bool
    var bundleID: String?
    var bundleURL: URL?
    var objectID: AudioObjectID
}

struct AudioProcessGroup: Identifiable, Hashable, Sendable {
    var id: String
    var title: String
    var processes: [AudioProcess]
}

extension AudioProcess.Kind {
    var defaultIcon: NSImage {
        switch self {
        case .process: NSWorkspace.shared.icon(for: .unixExecutable)
        case .app: NSWorkspace.shared.icon(for: .applicationBundle)
        }
    }
}

extension AudioProcess {
    var icon: NSImage {
        guard let bundleURL else { return kind.defaultIcon }
        let image = NSWorkspace.shared.icon(forFile: bundleURL.path)
        image.size = NSSize(width: 20, height: 20)
        return image
    }
}

extension String: @retroactive LocalizedError {
    public var errorDescription: String? { self }
}

@MainActor
@available(macOS 14.0, *)
@Observable
final class AudioProcessController {

    private let logger = Logger(subsystem: "com.stratten.basil", category: String(describing: AudioProcessController.self))

    private(set) var processes = [AudioProcess]() {
        didSet {
            guard processes != oldValue else { return }

            processGroups = AudioProcessGroup.groups(with: processes)
        }
    }

    private(set) var processGroups = [AudioProcessGroup]()

    private var cancellables = Set<AnyCancellable>()

    /// Logger for the background build, which runs off the main actor.
    private nonisolated static let buildLogger = Logger(subsystem: "com.stratten.basil", category: "AudioProcessController")

    /// Reloads slower than this, or ones that covered several notifications, are written to the desktop log so a main-thread stall can be matched to its cause.
    private static let slowReloadLogThresholdMilliseconds = 250

    /// True once the first delivery after `activate()` has been built. That one stays synchronous because callers read `processGroups` right after activating.
    private(set) var hasLoadedProcesses = false
    private(set) var isReloadInFlight = false
    private var pendingApps: RunningApplicationsBox?
    private(set) var pendingNotificationCount = 0
    /// How many background rebuilds have started; lets tests prove that bursts coalesce.
    private(set) var backgroundReloadCount = 0

    func activate() {
        logger.debug(#function)

        NSWorkspace.shared
            .publisher(for: \.runningApplications, options: [.initial, .new])
            .map { $0.filter({ $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) }
            .sink { [weak self] apps in
                guard let self else { return }
                self.handleRunningApplicationsChange(apps)
            }
            .store(in: &cancellables)
    }

    /// Every running-application change used to rebuild the whole list on the main actor, and each rebuild makes a blocking round trip to `coreaudiod` per audio process, so a burst of launches and quits froze the app for seconds. After the first load the build now runs on a background task, and notifications that arrive while it runs collapse into one more rebuild with the latest application list.
    func handleRunningApplicationsChange(_ apps: [NSRunningApplication]) {
        guard hasLoadedProcesses else {
            hasLoadedProcesses = true
            let started = ContinuousClock.now
            apply(Self.buildProcesses(apps: apps), notifications: 1, started: started)
            return
        }

        pendingNotificationCount += 1
        guard !isReloadInFlight else {
            pendingApps = RunningApplicationsBox(apps: apps)
            return
        }
        startBackgroundReload(apps: apps)
    }

    private func startBackgroundReload(apps: [NSRunningApplication]) {
        isReloadInFlight = true
        backgroundReloadCount += 1
        let notifications = pendingNotificationCount
        pendingNotificationCount = 0
        let box = RunningApplicationsBox(apps: apps)
        let started = ContinuousClock.now
        Task.detached(priority: .utility) { [weak self] in
            let result = Self.buildProcesses(apps: box.apps)
            await self?.finishBackgroundReload(result, notifications: notifications, started: started)
        }
    }

    private func finishBackgroundReload(_ result: Result<[AudioProcess], Error>, notifications: Int, started: ContinuousClock.Instant) {
        apply(result, notifications: notifications, started: started)
        if let next = pendingApps {
            pendingApps = nil
            startBackgroundReload(apps: next.apps)
        } else {
            isReloadInFlight = false
        }
    }

    private func apply(_ result: Result<[AudioProcess], Error>, notifications: Int, started: ContinuousClock.Instant) {
        switch result {
        case .success(let updatedProcesses):
            processes = updatedProcesses
        case .failure(let error):
            logger.error("Error reading process list: \(error)")
        }

        let components = started.duration(to: ContinuousClock.now).components
        let milliseconds = Int(components.seconds) * 1000 + Int(components.attoseconds / 1_000_000_000_000_000)
        if milliseconds >= Self.slowReloadLogThresholdMilliseconds || notifications > 1 {
            DevLogger.shared.warning(
                "Audio process list reload took \(milliseconds) ms for \(processes.count) processes and covered \(notifications) application-list notification(s)",
                context: "AudioProcessController"
            )
        }
    }

    /// Reads the CoreAudio process list and builds an `AudioProcess` for each entry. Safe off the main actor: it touches no controller state.
    private nonisolated static func buildProcesses(apps: [NSRunningApplication]) -> Result<[AudioProcess], Error> {
        do {
            let objectIdentifiers = try AudioObjectID.readProcessList()

            let updatedProcesses: [AudioProcess] = objectIdentifiers.compactMap { objectID in
                do {
                    let proc = try AudioProcess(objectID: objectID, runningApplications: apps)

                    #if DEBUG
                    if UserDefaults.standard.bool(forKey: "ACDumpProcessInfo") {
                        buildLogger.debug("[PROCESS] \(String(describing: proc))")
                    }
                    #endif

                    return proc
                } catch {
                    buildLogger.warning("Failed to initialize process with object ID #\(objectID): \(error)")
                    return nil
                }
            }

            return .success(updatedProcesses.sorted {
                $0.name.localizedStandardCompare($1.name) == .orderedAscending
            })
        } catch {
            return .failure(error)
        }
    }
}

/// Hands the running-application snapshot to the background build. `NSRunningApplication` is not declared `Sendable`, but the properties read from it (`processIdentifier`, `localizedName`, `bundleURL`, `bundleIdentifier`) are safe to read from any thread, and the meeting-detection probe already reads it off the main actor.
private struct RunningApplicationsBox: @unchecked Sendable {
    let apps: [NSRunningApplication]
}

private extension AudioProcess {
    init(app: NSRunningApplication, objectID: AudioObjectID) {
        let name = app.localizedName ?? app.bundleURL?.deletingPathExtension().lastPathComponent ?? app.bundleIdentifier?.components(separatedBy: ".").last ?? "Unknown \(app.processIdentifier)"

        self.init(
            id: app.processIdentifier,
            kind: .app,
            name: name,
            audioActive: objectID.readProcessIsRunning(),
            bundleID: app.bundleIdentifier,
            bundleURL: app.bundleURL,
            objectID: objectID
        )
    }

    init(objectID: AudioObjectID, runningApplications apps: [NSRunningApplication]) throws {
        let pid: pid_t = try objectID.read(kAudioProcessPropertyPID, defaultValue: -1)

        if let app = apps.first(where: { $0.processIdentifier == pid }) {
            self.init(app: app, objectID: objectID)
        } else {
            try self.init(objectID: objectID, pid: pid)
        }
    }

    init(objectID: AudioObjectID, pid: pid_t) throws {
        let bundleID = objectID.readProcessBundleID()
        let bundleURL: URL?
        let name: String

        if let info = processInfo(for: pid) {
            let parentBundleURL = URL(fileURLWithPath: info.path).parentBundleURL()
            let parentBundleID = bundleID
                .map { AudioAppNameResolver.parentBundleID(from: $0) }
                ?? parentBundleURL.flatMap { Bundle(url: $0)?.bundleIdentifier }
            if let parentBundleID, parentBundleURL != nil {
                name = AudioAppNameResolver.displayName(forBundleID: parentBundleID, bundleURL: parentBundleURL, pid: pid)
                bundleURL = parentBundleURL
            } else {
                name = info.name
                bundleURL = parentBundleURL
            }
        } else if let id = bundleID?.lastReverseDNSComponent {
            name = id
            bundleURL = nil
        } else {
            name = "Unknown (\(pid))"
            bundleURL = nil
        }

        self.init(
            id: pid,
            kind: bundleURL?.isApp == true ? .app : .process,
            name: name,
            audioActive: objectID.readProcessIsRunning(),
            bundleID: bundleID.flatMap { $0.isEmpty ? nil : $0 },
            bundleURL: bundleURL,
            objectID: objectID
        )
    }
}

// MARK: - Grouping

extension AudioProcessGroup {
    static func groups(with processes: [AudioProcess]) -> [AudioProcessGroup] {
        // First create a special group for processes with active audio
        let activeAudioProcesses = processes.filter { $0.audioActive }
        
        // Create normal groups by kind, but exclude processes that are already in the active audio group
        var byKind = [AudioProcess.Kind: AudioProcessGroup]()
        for process in processes where !process.audioActive {
            byKind[process.kind, default: .init(for: process.kind)].processes.append(process)
        }
        
        // Start with the active audio group if it has processes
        var result: [AudioProcessGroup] = []
        
        if !activeAudioProcesses.isEmpty {
            let activeGroup = AudioProcessGroup(
                id: "active-audio",
                title: "Currently Producing Audio",
                processes: activeAudioProcesses.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            )
            result.append(activeGroup)
        }
        
        // Add the remaining groups sorted by title
        result.append(contentsOf: byKind.values.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending })
        
        return result
    }
}

extension AudioProcessGroup {
    init(for kind: AudioProcess.Kind) {
        self.init(id: kind.rawValue, title: kind.groupTitle, processes: [])
    }
}

extension AudioProcess.Kind {
    var groupTitle: String {
        switch self {
        case .process: "Processes"
        case .app: "Apps"
        }
    }
}

// MARK: - Helpers

private func processInfo(for pid: pid_t) -> (name: String, path: String)? {
    let nameBuffer = UnsafeMutablePointer<UInt8>.allocate(capacity: Int(MAXPATHLEN))
    let pathBuffer = UnsafeMutablePointer<UInt8>.allocate(capacity: Int(MAXPATHLEN))

    defer {
        nameBuffer.deallocate()
        pathBuffer.deallocate()
    }

    let nameLength = proc_name(pid, nameBuffer, UInt32(MAXPATHLEN))
    let pathLength = proc_pidpath(pid, pathBuffer, UInt32(MAXPATHLEN))

    guard nameLength > 0, pathLength > 0 else {
        return nil
    }

    let name = String(cString: nameBuffer)
    let path = String(cString: pathBuffer)

    return (name, path)
}

private extension String {
    var lastReverseDNSComponent: String? {
        components(separatedBy: ".").last.flatMap { $0.isEmpty ? nil : $0 }
    }
}

private extension URL {
    func parentBundleURL(maxDepth: Int = 8) -> URL? {
        var depth = 0
        var url = deletingLastPathComponent()
        while depth < maxDepth, !url.isBundle {
            url = url.deletingLastPathComponent()
            depth += 1
        }
        return url.isBundle ? url : nil
    }

    var isBundle: Bool {
        (try? resourceValues(forKeys: [.contentTypeKey]))?.contentType?.conforms(to: .bundle) == true
    }

    var isApp: Bool {
        (try? resourceValues(forKeys: [.contentTypeKey]))?.contentType?.conforms(to: .application) == true
    }
} 