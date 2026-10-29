import Foundation

/// Runs the window capture AppleScript in a child `osascript` process so the main thread is never blocked while System Events and `screencapture` do their work.
enum WindowCaptureProcessRunner {
    enum Outcome: Equatable {
        /// The script ran and printed this trimmed text.
        case output(String)
        /// `osascript` could not do the job in a way the in-process path might, such as a privacy denial or a launch failure. The caller falls back to the in-process path.
        case unavailable(String)
        /// The script ran and failed. Falling back would repeat the same failure.
        case failed(String)
    }

    /// Safety bound only. Completion is detected from process exit.
    static let defaultTimeoutSeconds: TimeInterval = 10

    private static let osascriptPath = "/usr/bin/osascript"

    /// Pure classification of a finished `osascript` run.
    static func classify(terminationStatus: Int32, standardOutput: String, standardError: String) -> Outcome {
        let output = standardOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        let errorText = standardError.trimmingCharacters(in: .whitespacesAndNewlines)
        if terminationStatus == 0 {
            return output.isEmpty ? .failed("AppleScript returned no output") : .output(output)
        }
        if errorText.contains("(-1743)") || errorText.contains("(-25211)") {
            return .unavailable("osascript was denied by macOS privacy controls: \(errorText)")
        }
        let detail = errorText.isEmpty ? "exit status \(terminationStatus)" : errorText
        return .failed("AppleScript execution failed: \(detail)")
    }

    /// Runs the script off the calling thread and returns when the process exits or the timeout elapses.
    static func run(script: String, timeoutSeconds: TimeInterval = defaultTimeoutSeconds) async -> Outcome {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                continuation.resume(returning: runBlocking(script: script, timeoutSeconds: timeoutSeconds))
            }
        }
    }

    private final class RunState: @unchecked Sendable {
        private let lock = NSLock()
        private var timedOutValue = false
        private var errorDataValue = Data()

        var timedOut: Bool {
            lock.lock()
            defer { lock.unlock() }
            return timedOutValue
        }

        var errorData: Data {
            lock.lock()
            defer { lock.unlock() }
            return errorDataValue
        }

        func markTimedOut() {
            lock.lock()
            timedOutValue = true
            lock.unlock()
        }

        func storeErrorData(_ data: Data) {
            lock.lock()
            errorDataValue = data
            lock.unlock()
        }
    }

    private static func runBlocking(script: String, timeoutSeconds: TimeInterval) -> Outcome {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: osascriptPath)
        process.arguments = ["-e", script]
        process.standardInput = FileHandle.nullDevice
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        do {
            try process.run()
        } catch {
            return .unavailable("osascript could not be launched: \(error.localizedDescription)")
        }

        let state = RunState()
        let watchdog = DispatchWorkItem {
            if process.isRunning {
                state.markTimedOut()
                process.terminate()
            }
        }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeoutSeconds, execute: watchdog)

        let errorReader = DispatchGroup()
        errorReader.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            state.storeErrorData(errorPipe.fileHandleForReading.readDataToEndOfFile())
            errorReader.leave()
        }
        let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
        errorReader.wait()
        process.waitUntilExit()
        watchdog.cancel()

        if state.timedOut {
            return .failed("AppleScript timed out after \(Int(timeoutSeconds)) seconds")
        }
        return classify(
            terminationStatus: process.terminationStatus,
            standardOutput: String(decoding: outputData, as: UTF8.self),
            standardError: String(decoding: state.errorData, as: UTF8.self)
        )
    }
}
