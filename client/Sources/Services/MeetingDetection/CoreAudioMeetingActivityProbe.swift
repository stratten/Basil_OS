import Foundation
import AppKit
import AudioToolbox

/// macOS implementation of `MeetingActivityProbing`.
///
/// Stateless and cheap: per probe it reads the CoreAudio process list and keeps
/// non-excluded processes whose `IsRunningInput` and `IsRunningOutput` are both
/// true. No audio tap is created, so there is no capture permission prompt and
/// the call is fast enough for a tight detection loop. Calendar context is
/// delegated to an optional `MeetingCalendarProviding`.
@available(macOS 14.0, *)
final class CoreAudioMeetingActivityProbe: MeetingActivityProbing {

    private let calendarProvider: MeetingCalendarProviding?

    init(calendarProvider: MeetingCalendarProviding? = nil) {
        self.calendarProvider = calendarProvider
    }

    func probe(excludedBundleIDs: [String]) async -> MeetingProbeResult {
        var excluded = Set(excludedBundleIDs)
        if let bundleIdentifier = Bundle.main.bundleIdentifier {
            excluded.insert(AudioAppNameResolver.parentBundleID(from: bundleIdentifier))
        }
        var activeApps: [DetectedMeetingApp] = []

        if let objectIDs = try? AudioObjectID.readProcessList() {
            for objectID in objectIDs {
                let pid: pid_t = (try? objectID.read(kAudioProcessPropertyPID, defaultValue: pid_t(-1))) ?? -1
                let rawBundleID = objectID.readProcessBundleID()
                    ?? NSRunningApplication(processIdentifier: pid)?.bundleIdentifier
                guard let rawBundleID else { continue }

                let bundleID = AudioAppNameResolver.parentBundleID(from: rawBundleID)
                guard !excluded.contains(bundleID) else { continue }
                guard objectID.readProcessIsRunningInput(),
                      objectID.readProcessIsRunningOutput() else { continue }

                let name = AudioAppNameResolver.displayName(forBundleID: bundleID, bundleURL: nil, pid: pid)
                let rawWindowTitle = Self.onScreenWindowTitle(forPID: pid)
                let windowTitle = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: rawWindowTitle, appName: name)
                activeApps.append(DetectedMeetingApp(name: name, bundleID: bundleID, pid: pid, windowTitle: windowTitle))
            }
        }

        let calendarEvent = await calendarProvider?.currentEvent()

        return MeetingProbeResult(activeMeetingApps: activeApps, currentCalendarEvent: calendarEvent)
    }

    /// First on-screen window title owned by `pid`. Mirrors the same
    /// `CGWindowListCopyWindowInfo` + `kCGWindowOwnerPID`/`kCGWindowName`
    /// lookup `TranscriptionWidgetViewModel.getActiveApplicationInfo()` uses
    /// for the frontmost app, generalized to an arbitrary pid since the
    /// meeting-detected app is not always frontmost. Reading another
    /// process's `kCGWindowName` requires Screen Recording permission
    /// (already required elsewhere in this app for window capture); when
    /// that permission is absent this simply returns `nil` and detection
    /// falls back to today's app-name-only behavior with no crash or
    /// regression.
    private static func onScreenWindowTitle(forPID pid: pid_t) -> String? {
        let options = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
        guard let windowsListInfo = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }
        for windowInfo in windowsListInfo {
            if let windowPID = windowInfo[kCGWindowOwnerPID as String] as? Int,
               windowPID == Int(pid),
               let title = windowInfo[kCGWindowName as String] as? String,
               !title.isEmpty {
                return title
            }
        }
        return nil
    }
}
