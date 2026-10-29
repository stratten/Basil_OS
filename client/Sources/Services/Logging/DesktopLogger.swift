import Foundation
import OSLog

/// Global print wrapper that also logs to desktop when enabled
func debugPrint(_ items: Any..., separator: String = " ", terminator: String = "\n") {
    // Standard print behavior
    let message = items.map { "\($0)" }.joined(separator: separator)
    print(message, terminator: terminator)
    
    // Also log to desktop if enabled
    Task { @MainActor in
        if DesktopLogger.shared.isEnabled {
            DesktopLogger.shared.log("[PRINT] \(message)", category: "Debug")
        }
    }
}

/// Debug logger that writes all application logs to desktop for troubleshooting packaged apps
@MainActor
final class DesktopLogger: ObservableObject {
    static let shared = DesktopLogger()
    
    @Published private(set) var isEnabled = false
    
    private var logFileURL: URL?
    private var logFileHandle: FileHandle?
    private let dateFormatter: DateFormatter
    private let sessionID: String
    
    private init() {
        self.sessionID = UUID().uuidString.prefix(8).description
        
        // Setup date formatter
        self.dateFormatter = DateFormatter()
        self.dateFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        
        // Check if logging was previously enabled (persist across sessions)
        // Only auto-enable in DEBUG builds to prevent log spam on user desktops
        #if DEBUG
        if BasilRuntimeProfile.userDefaults.bool(forKey: "DesktopLoggingEnabled") {
            enableDesktopLogging()
        }
        #endif
    }
    
    func enableDesktopLogging() {
        // Prevent enabling in Release builds
        #if !DEBUG
        return
        #endif
        
        guard !isEnabled else { return }
        
        do {
            // Create log directory on Desktop
            let desktopURL = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first!
            let logDirURL = desktopURL.appendingPathComponent("BasilDebugLogs", isDirectory: true)
            
            // Create directory if it doesn't exist
            try FileManager.default.createDirectory(at: logDirURL, withIntermediateDirectories: true)
            
            // Create session-specific log file
            let timestampFormatter = DateFormatter()
            timestampFormatter.dateFormat = "yyyyMMdd_HHmmss"
            let timestamp = timestampFormatter.string(from: Date())
            let fileName = "Basil_\(timestamp)_\(sessionID).log"
            logFileURL = logDirURL.appendingPathComponent(fileName)
            
            // Create and open file for writing
            FileManager.default.createFile(atPath: logFileURL!.path, contents: nil)
            logFileHandle = try FileHandle(forWritingTo: logFileURL!)
            
            // Write header
            let header = """
            =====================================
            BASIL DEBUG LOG SESSION
            =====================================
            Session ID: \(sessionID)
            Started: \(dateFormatter.string(from: Date()))
            App Version: \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "Unknown")
            Build: \(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "Unknown")
            macOS Version: \(ProcessInfo.processInfo.operatingSystemVersionString)
            =====================================
            
            """
            writeToLog(header)
            
            isEnabled = true
            BasilRuntimeProfile.userDefaults.set(true, forKey: "DesktopLoggingEnabled")
            
            // Start intercepting logs
            setupLogInterception()
            
            writeToLog("✅ Desktop logging enabled")
            print("✅ Desktop logging enabled - logs will be written to: \(logFileURL!.path)")
            
        } catch {
            print("❌ Failed to enable desktop logging: \(error)")
        }
    }
    
    func disableDesktopLogging() {
        guard isEnabled else { return }
        
        writeToLog("🛑 Desktop logging disabled")
        
        logFileHandle?.closeFile()
        logFileHandle = nil
        logFileURL = nil
        isEnabled = false
        
        BasilRuntimeProfile.userDefaults.set(false, forKey: "DesktopLoggingEnabled")
        
        print("🛑 Desktop logging disabled")
    }
    
    private func setupLogInterception() {
        // This is a simplified approach - we'll enhance the existing DevLogger
        // to also write to our desktop log when enabled
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleLogMessage),
            name: NSNotification.Name("DesktopLogMessage"),
            object: nil
        )
    }
    
    @objc private func handleLogMessage(notification: Notification) {
        guard let message = notification.object as? String else { return }
        writeToLog(message)
    }
    
    private func writeToLog(_ message: String) {
        guard isEnabled, let fileHandle = logFileHandle else { return }
        
        let timestamp = dateFormatter.string(from: Date())
        let logEntry = "[\(timestamp)] \(message)\n"
        
        if let data = logEntry.data(using: .utf8) {
            fileHandle.write(data)
        }
    }
    
    // Public method for other components to log to desktop
    func log(_ message: String, category: String = "General") {
        guard isEnabled else { return }
        writeToLog("[\(category)] \(message)")
    }
    
    deinit {
        // Handle cleanup directly in deinit since we can't call main actor methods
        logFileHandle?.closeFile()
        logFileHandle = nil
        logFileURL = nil
        BasilRuntimeProfile.userDefaults.set(false, forKey: "DesktopLoggingEnabled")
    }
} 