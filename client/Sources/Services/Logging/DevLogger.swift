import Foundation

#if DEBUG
/// Development logger that sends logs to the backend console
final class DevLogger {
    static let shared = DevLogger()
    private let api = APIClient.shared
    
    private init() {}
    
    func debug(_ message: String, context: String? = nil) {
        api.devLog("[DEBUG] \(message)", context: context)
        logToDesktop("[DEBUG] \(message)", context: context)
    }
    
    func info(_ message: String, context: String? = nil) {
        api.devLog("[INFO] \(message)", context: context)
        logToDesktop("[INFO] \(message)", context: context)
    }
    
    func warning(_ message: String, context: String? = nil) {
        api.devLog("[WARN] \(message)", context: context)
        logToDesktop("[WARN] \(message)", context: context)
    }
    
    func error(_ message: String, context: String? = nil) {
        api.devLog("[ERROR] \(message)", context: context)
        logToDesktop("[ERROR] \(message)", context: context)
    }
    
    /// Log with file and line information
    func trace(_ message: String, file: String = #file, line: Int = #line, context: String? = nil) {
        let fileName = (file as NSString).lastPathComponent
        let trace = "\(fileName):\(line) - \(message)"
        api.devLog("[TRACE] \(trace)", context: context)
        logToDesktop("[TRACE] \(trace)", context: context)
    }
    
    private func logToDesktop(_ message: String, context: String?) {
        Task { @MainActor in
            if DesktopLogger.shared.isEnabled {
                let contextString = context != nil ? "[\(context!)]" : ""
                DesktopLogger.shared.log("\(contextString) \(message)", category: context ?? "General")
            }
        }
    }
}
#else
// Release build: DevLogger sends to DesktopLogger if enabled
final class DevLogger {
    static let shared = DevLogger()
    private init() {}
    
    func debug(_ message: String, context: String? = nil) {
        logToDesktop("[DEBUG] \(message)", context: context)
    }
    
    func info(_ message: String, context: String? = nil) {
        logToDesktop("[INFO] \(message)", context: context)
    }
    
    func warning(_ message: String, context: String? = nil) {
        logToDesktop("[WARN] \(message)", context: context)
    }
    
    func error(_ message: String, context: String? = nil) {
        logToDesktop("[ERROR] \(message)", context: context)
    }
    
    func trace(_ message: String, file: String = #file, line: Int = #line, context: String? = nil) {
        let fileName = (file as NSString).lastPathComponent
        let trace = "\(fileName):\(line) - \(message)"
        logToDesktop("[TRACE] \(trace)", context: context)
    }
    
    private func logToDesktop(_ message: String, context: String?) {
        Task { @MainActor in
            if DesktopLogger.shared.isEnabled {
                let contextString = context != nil ? "[\(context!)]" : ""
                DesktopLogger.shared.log("\(contextString) \(message)", category: context ?? "General")
            }
        }
    }
}
#endif 