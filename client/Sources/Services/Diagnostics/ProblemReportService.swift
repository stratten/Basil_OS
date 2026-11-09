import AppKit
import Foundation

/// The facts the app sends when the user reports a problem. `detail` is a native return code or similar and never conversation or prompt text.
struct ProblemReportRequestBody: Encodable, Equatable {
    let source: String
    let detail: String?
    let appVersion: String
    let macosVersion: String
}

/// What the backend returns after it wrote the diagnostics bundle on this Mac.
struct ProblemReportResult: Decodable, Equatable {
    let bundlePath: String
    let issueUrl: String
    let logExcerptAvailable: Bool
}

/// Report a problem: asks the backend for a redacted diagnostics bundle, shows it in Finder, and opens a pre-filled GitHub issue.
/// Nothing is uploaded. The user attaches the bundle to the issue if they choose to.
enum ProblemReportService {
    static let issueRepositoryPath = "/stratten/Basil_OS/issues/new"
    static let fallbackIssueURL = URL(string: "https://github.com/stratten/Basil_OS/issues/new")!

    static func appVersionDescription(bundle: Bundle = .main) -> String {
        let version = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
        let build = bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        guard let build, !build.isEmpty, build != version else { return version }
        return "\(version) (\(build))"
    }

    static func macOSVersionDescription(processInfo: ProcessInfo = .processInfo) -> String {
        let version = processInfo.operatingSystemVersion
        return "macOS \(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
    }

    static func makeRequestBody(
        source: String,
        detail: String?,
        bundle: Bundle = .main,
        processInfo: ProcessInfo = .processInfo
    ) -> ProblemReportRequestBody {
        let trimmedDetail = detail?.trimmingCharacters(in: .whitespacesAndNewlines)
        return ProblemReportRequestBody(
            source: source,
            detail: (trimmedDetail?.isEmpty ?? true) ? nil : trimmedDetail,
            appVersion: appVersionDescription(bundle: bundle),
            macosVersion: macOSVersionDescription(processInfo: processInfo)
        )
    }

    /// The issue link to open. Only a GitHub new-issue link for this repository is accepted, so a malformed or unexpected backend value falls back to the plain new-issue page.
    static func issueURLToOpen(from result: ProblemReportResult?) -> URL {
        guard let result,
              let url = URL(string: result.issueUrl),
              url.scheme?.lowercased() == "https",
              url.host?.lowercased() == "github.com",
              url.path == issueRepositoryPath else {
            return fallbackIssueURL
        }
        return url
    }

    /// Writes the bundle, reveals it in Finder, and opens the pre-filled issue unless `openIssue` is false (the Show logs action only reveals the bundle). If the backend cannot build the bundle, the plain issue page still opens when `openIssue` is true so the report is never lost.
    @MainActor
    static func report(source: String, detail: String?, openIssue: Bool = true, api: APIClient = .shared, workspace: NSWorkspace = .shared) async {
        let body = makeRequestBody(source: source, detail: detail)
        var result: ProblemReportResult?
        do {
            result = try await api.post("/diagnostics/problem-report", body: body, decoding: ProblemReportResult.self)
        } catch {
            DevLogger.shared.error("[ProblemReport] Could not build the diagnostics bundle: \(error)", context: "ProblemReport")
        }

        if result == nil && !openIssue {
            let alert = NSAlert()
            alert.messageText = "Basil couldn't save the diagnostics bundle"
            alert.informativeText = "Please try again, or use Report a Problem from the Basil menu."
            alert.alertStyle = .warning
            alert.runModal()
        }

        if let result {
            let bundleURL = URL(fileURLWithPath: result.bundlePath)
            if FileManager.default.fileExists(atPath: bundleURL.path) {
                workspace.activateFileViewerSelecting([bundleURL])
            }
        }
        if openIssue {
            _ = BridgeOpenPolicy.openExternalURL(issueURLToOpen(from: result), workspace: workspace)
        }
    }
}
