import Foundation
import AppKit
import CoreGraphics

/// Identifies one specific browser window by the geometry and title the backend read from the browser's own AppleScript dictionary.
///
/// A browser's AppleScript window id is the browser's internal id, not the macOS `CGWindowID`, so the window is found by matching its on-screen frame and title instead.
struct BrowserWindowCaptureTarget: Equatable {
    /// Process name as reported by Core Graphics, such as "Google Chrome".
    let ownerName: String
    /// Frame in global display coordinates with a top-left origin, which is what both Chrome's and Safari's AppleScript `bounds` and `kCGWindowBounds` use.
    let bounds: CGRect
    /// Title of the window's active tab, used to break ties between windows that share a frame.
    let title: String?
}

extension BrowserWindowCaptureTarget {
    /// Builds a target from the backend's `window_target` JSON: `{"owner_name": String, "bounds": {"x","y","width","height"}, "title": String?}`. Returns nil when the payload is absent or incomplete, so a malformed target falls back to the ordinary active-window capture rather than failing.
    init?(payload: Any?) {
        guard let dictionary = payload as? [String: Any],
              let ownerName = dictionary["owner_name"] as? String,
              !ownerName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let boundsDictionary = dictionary["bounds"] as? [String: Any],
              let x = (boundsDictionary["x"] as? NSNumber)?.doubleValue,
              let y = (boundsDictionary["y"] as? NSNumber)?.doubleValue,
              let width = (boundsDictionary["width"] as? NSNumber)?.doubleValue,
              let height = (boundsDictionary["height"] as? NSNumber)?.doubleValue,
              width > 0, height > 0 else {
            return nil
        }
        self.init(
            ownerName: ownerName,
            bounds: CGRect(x: x, y: y, width: width, height: height),
            title: dictionary["title"] as? String
        )
    }
}

/// One window as listed by `CGWindowListCopyWindowInfo`.
struct BrowserWindowCandidate: Equatable {
    let windowID: CGWindowID
    let ownerName: String
    let ownerPID: pid_t
    let title: String
    let bounds: CGRect
    let layer: Int
}

/// Captures a specific browser window by `CGWindowID` with `screencapture -l`, which renders the window itself and therefore does not depend on which app is frontmost or what is covering the window.
enum BrowserWindowCaptureService {
    /// Allowed difference in points between the browser-reported frame and the Core Graphics frame.
    static let boundsTolerance: CGFloat = 6

    // MARK: - Matching

    enum MatchOutcome: Equatable {
        case matched(BrowserWindowCandidate)
        case noWindow
        case ambiguous(count: Int)
    }

    /// Pure selection of the window that corresponds to `target`.
    static func match(target: BrowserWindowCaptureTarget, candidates: [BrowserWindowCandidate]) -> MatchOutcome {
        let sameOwner = candidates.filter {
            $0.layer == 0 && $0.ownerName.caseInsensitiveCompare(target.ownerName) == .orderedSame
        }
        let sameFrame = sameOwner.filter { boundsAgree($0.bounds, target.bounds) }
        if sameFrame.isEmpty { return .noWindow }
        if sameFrame.count == 1 { return .matched(sameFrame[0]) }

        let trimmedTitle = (target.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedTitle.isEmpty {
            let titled = sameFrame.filter { $0.title.localizedCaseInsensitiveContains(trimmedTitle) }
            if titled.count == 1 { return .matched(titled[0]) }
            if titled.count > 1 { return .ambiguous(count: titled.count) }
        }
        return .ambiguous(count: sameFrame.count)
    }

    static func boundsAgree(_ lhs: CGRect, _ rhs: CGRect) -> Bool {
        abs(lhs.origin.x - rhs.origin.x) <= boundsTolerance
            && abs(lhs.origin.y - rhs.origin.y) <= boundsTolerance
            && abs(lhs.size.width - rhs.size.width) <= boundsTolerance
            && abs(lhs.size.height - rhs.size.height) <= boundsTolerance
    }

    // MARK: - Window listing

    /// Lists on-screen windows. A minimized window, or one on another Space, is not returned and cannot be captured.
    static func onScreenCandidates() -> [BrowserWindowCandidate] {
        guard let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
            return []
        }
        return info.compactMap { entry -> BrowserWindowCandidate? in
            guard let number = entry[kCGWindowNumber as String] as? UInt32,
                  let owner = entry[kCGWindowOwnerName as String] as? String,
                  let pid = entry[kCGWindowOwnerPID as String] as? Int32,
                  let layer = entry[kCGWindowLayer as String] as? Int,
                  let boundsDictionary = entry[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: boundsDictionary) else {
                return nil
            }
            return BrowserWindowCandidate(
                windowID: CGWindowID(number),
                ownerName: owner,
                ownerPID: pid,
                title: entry[kCGWindowName as String] as? String ?? "",
                bounds: bounds,
                layer: layer
            )
        }
    }

    // MARK: - Capture

    /// Captures the window that matches `target`. The browser is never activated or raised.
    static func capture(target: BrowserWindowCaptureTarget) async -> WindowCaptureService.CaptureResult {
        let outcome = match(target: target, candidates: onScreenCandidates())
        let candidate: BrowserWindowCandidate
        switch outcome {
        case .matched(let found):
            candidate = found
        case .noWindow:
            return .failure(
                appName: target.ownerName,
                windowTitle: target.title ?? "",
                error: "The Basil automation window was not found on screen. It may be minimized or on another Space."
            )
        case .ambiguous(let count):
            return .failure(
                appName: target.ownerName,
                windowTitle: target.title ?? "",
                error: "\(count) \(target.ownerName) windows share the automation window's frame, so the correct one could not be chosen."
            )
        }

        let bundleIdentifier = NSRunningApplication(processIdentifier: candidate.ownerPID)?.bundleIdentifier
        let imagePath = NSHomeDirectory() + "/.basil/data/temp/browser_capture_\(Int(Date().timeIntervalSince1970 * 1000)).png"
        let windowID = candidate.windowID

        let failureMessage: String? = await Task.detached(priority: .userInitiated) {
            runScreencapture(windowID: windowID, outputPath: imagePath)
        }.value

        if let failureMessage {
            return .failure(
                appName: candidate.ownerName,
                windowTitle: candidate.title,
                bundleIdentifier: bundleIdentifier,
                error: failureMessage
            )
        }
        return .success(
            imagePath: imagePath,
            appName: candidate.ownerName,
            windowTitle: candidate.title,
            bundleIdentifier: bundleIdentifier,
            perceptualHash: PerceptualHashService.differenceHash(imagePath: imagePath)
        )
    }

    /// Returns nil on success, or a message describing the failure.
    private static func runScreencapture(windowID: CGWindowID, outputPath: String) -> String? {
        let directory = (outputPath as NSString).deletingLastPathComponent
        do {
            try FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true, attributes: nil)
        } catch {
            return "Could not create the capture folder: \(error.localizedDescription)"
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        // -x silences the shutter sound, -o omits the window shadow, -l captures the window with this id.
        process.arguments = ["-x", "-o", "-l", String(windowID), outputPath]
        process.standardInput = FileHandle.nullDevice
        let errorPipe = Pipe()
        process.standardError = errorPipe
        process.standardOutput = FileHandle.nullDevice

        do {
            try process.run()
        } catch {
            return "screencapture could not be launched: \(error.localizedDescription)"
        }
        let errorText = String(decoding: errorPipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            return errorText.isEmpty ? "screencapture exited with status \(process.terminationStatus)" : "screencapture failed: \(errorText)"
        }
        let size = (try? FileManager.default.attributesOfItem(atPath: outputPath)[.size] as? Int) ?? 0
        guard size >= 1000 else {
            return "Screen recording permission likely denied: the captured window image was only \(size) bytes."
        }
        return nil
    }
}
