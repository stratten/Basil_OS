import Foundation
import os

/// Errors that can occur in API operations
enum APIError: Error {
    case connectionFailed(String)
    case invalidResponse
    case decodingFailed(Error)
    case backendNotAvailable
    case invalidURL
    case serverError(statusCode: Int)
}

extension APIError {
    /// Wraps an underlying network-layer error for `.connectionFailed`.
    /// `URLError.cancelled.localizedDescription` comes back from Foundation
    /// as "cancelled" (its own spelling, not ours) with no further context;
    /// this rewords it with the American spelling and an explanation of what
    /// actually happened, instead of forwarding Foundation's bare text.
    static func connectionFailed(from underlying: Error) -> APIError {
        if (underlying as? URLError)?.code == .cancelled {
            return .connectionFailed("the request was canceled before it finished")
        }
        return .connectionFailed(underlying.localizedDescription)
    }
}

extension APIError: LocalizedError {
    /// Without this conformance, Swift bridges every case to the generic
    /// NSError description "The operation couldn't be completed. (BasilClient.APIError
    /// error N.)" where N is just the case's declaration index -- the actual
    /// associated-value detail (e.g. the underlying URLSession error, or which
    /// HTTP status came back) is silently discarded and never reaches the UI
    /// or logs. This surfaces the real diagnostic instead.
    var errorDescription: String? {
        switch self {
        case .connectionFailed(let detail):
            return "Could not reach the Basil backend: \(detail)"
        case .invalidResponse:
            return "The Basil backend returned a response that could not be understood."
        case .decodingFailed(let underlying):
            return "Could not parse the Basil backend's response: \(underlying.localizedDescription)"
        case .backendNotAvailable:
            return "The Basil backend is not available right now."
        case .invalidURL:
            return "Could not build a valid request URL."
        case .serverError(let statusCode):
            return "The Basil backend returned an error (HTTP \(statusCode))."
        }
    }
}

/// Response from API operations
struct OperationResponse: Codable {
    let operation: String
    let status: String
    let details: String?
    
    init(operation: String = "unknown", status: String, details: String? = nil) {
        self.operation = operation
        self.status = status
        self.details = details
    }
}

/// Empty body for requests that don't need data
struct EmptyBody: Codable {}

/// Client for communicating with the Python backend
final class APIClient {
    // MARK: - Properties
    static let shared = APIClient()
    static var isBackendShuttingDown: Bool = false
    let fixedBackendURL: URL?
    let fixedBackendPort: Int?
    var currentPort: Int
    var isBackendAvailable = false
    let logger = Logger(subsystem: Bundle.main.bundleIdentifier ?? "com.basil.client", category: "APIClient")
    var cachedTranscriptionSettings: TranscriptionSettings?
    var cachedBehaviorSettings: BehaviorSettings?
    var cachedAgentTaskSettings: AgentTaskSettings?
    var cachedAppearanceSettings: AppearanceSettings?
    var cachedGeneralSettings: GeneralSettings?
    
    var baseURL: String {
        if let fixedBackendURL {
            return fixedBackendURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }
        return "http://localhost:\(currentPort)"
    }
    
    #if DEBUG
    private var lastLogTime: Date = Date.distantPast
    private let minLogInterval: TimeInterval = 0.1 // Maximum 10 logs per second
    
    /// Send a development log to the backend for unified console output
    func devLog(_ message: String, level: String = "INFO", context: String? = nil) {
        // Check the shutdown flag before attempting to log
        guard !APIClient.isBackendShuttingDown else {
            // Optionally, print to local console if backend is shutting down
            // print("[LOG_SUPPRESSED_SHUTDOWN] \(message)") 
            return
        }
        guard isBackendAvailable else { return }
        
        // Rate limiting: only send logs every 100ms to prevent flooding
        let now = Date()
        guard now.timeIntervalSince(lastLogTime) >= minLogInterval else { 
            return 
        }
        lastLogTime = now
        
        // Format the message with any context if provided
        let formattedMessage = context != nil ? "[\(context!)] \(message)" : message
        // Send it to the backend without waiting for response
        Task {
            guard let url = URL(string: "\(baseURL)/settings/dev/log") else { return }
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("text/plain", forHTTPHeaderField: "Content-Type")
            request.httpBody = formattedMessage.data(using: .utf8)
            request.timeoutInterval = 2.0 // Short timeout for log requests
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                guard let httpResponse = response as? HTTPURLResponse,
                      (200...299).contains(httpResponse.statusCode) else {
                    print("Failed to send log: \(formattedMessage)")
                    return
                }
            } catch {
                // Silently ignore log request failures to prevent cascading issues
                // print("Error sending log: \(error)")
            }
        }
    }
    #endif
    
    // MARK: - Initialization
    static func backendURLOverride(arguments: [String]) -> URL? {
        for index in arguments.indices where arguments[index] == "--backend-url" {
            let valueIndex = arguments.index(after: index)
            guard valueIndex < arguments.endIndex,
                  let url = URL(string: arguments[valueIndex]),
                  url.scheme == "http",
                  let host = url.host?.lowercased(),
                  host == "localhost" || host == "127.0.0.1",
                  url.port != nil,
                  url.user == nil,
                  url.password == nil,
                  url.path.isEmpty || url.path == "/" else {
                return nil
            }
            return url
        }
        return nil
    }

    static func backendPortOverride(arguments: [String]) -> Int? {
        backendURLOverride(arguments: arguments)?.port
    }

    init(performsInitialHealthCheck: Bool = true) {
        fixedBackendURL = BasilRuntimeProfile.backendURL ?? Self.backendURLOverride(arguments: CommandLine.arguments)
        fixedBackendPort = fixedBackendURL?.port
        if let fixedBackendURL {
            #if DEBUG
            logger.info("📡 Using fixed backend URL: \(fixedBackendURL.absoluteString)")
            #endif
        }
        currentPort = fixedBackendPort ?? Self.readPortFromFile() ?? 8000
        
        // Perform an initial health check to update port or availability
        if performsInitialHealthCheck {
            Task {
                await updatePortAndCheckStatus()
            }
        }
    }
    
    // MARK: - Settings Methods
    // (Moved to APIClient_settings.swift)
    
    // MARK: - Public Methods
    /// Gets the port number being used by the backend
    static func getServerPort() -> Int {
        readPortFromFile() ?? 8000
    }
    
    // (post moved to APIClient_networking.swift)
    
    // MARK: - Networking Core Methods
    // (get, put, delete, post, postForData, getSync, putSync, and readPortFromFile moved to APIClient_networking.swift)
    
    // MARK: - API Model Management Methods
    // (updateApiProviderSettings, updateApiModelSettings, setApiKey, and testApiKey moved to APIClient_settings.swift)
    
    // MARK: - Synchronous Methods
    // (getSync moved to APIClient_networking.swift)
    
    // MARK: - Private Methods
    func updatePortAndCheckStatus() async {
        // A test or support client launched with --backend-url must remain attached
        // to its explicit backend rather than following the shared port-file state.
        if fixedBackendURL == nil,
           let newPort = Self.readPortFromFile(),
           newPort != self.currentPort {
            self.currentPort = newPort
            #if DEBUG
            logger.info("🔄 Updated backend port to: \(self.currentPort)")
            #endif
        }
        
        // Check backend status with timeout and retry logic
        var healthCheckURL: URL?
        do {
            healthCheckURL = URL(string: self.baseURL + "/health")!
            var request = URLRequest(url: healthCheckURL!)
            request.timeoutInterval = 5.0 // Short timeout for health checks
            
            let (_, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                let wasAvailable = self.isBackendAvailable
                self.isBackendAvailable = (200...299).contains(httpResponse.statusCode)
                
                if wasAvailable != self.isBackendAvailable {
                    #if DEBUG
                    logger.info("🔌 Backend status changed: \(self.isBackendAvailable ? "Available" : "Unavailable")")
                    #endif
                }
            }
        } catch {
            // Only mark as unavailable on connection refused or similar definitive errors
            // Don't mark as unavailable for transient network issues like timeouts
            let errorString = error.localizedDescription.lowercased()
            let isDefinitiveError = errorString.contains("connection refused") || 
                                   errorString.contains("no route to host") ||
                                   errorString.contains("network is unreachable")
            
            if isDefinitiveError {
                if self.isBackendAvailable {
                    #if DEBUG
                    logger.error("❌ Backend definitely unavailable (connection refused): \(error.localizedDescription)")
                    #endif
                }
                self.isBackendAvailable = false
            } else {
                // For transient errors (timeouts, etc.), don't change availability status
                #if DEBUG
                if self.isBackendAvailable {
                    logger.warning("⚠️ Transient network error for health check, keeping current status: \(error.localizedDescription)")
                } else {
                    logger.warning("⚠️ Health check failed but backend was already marked unavailable: \(error.localizedDescription)")
                }
                #endif
            }
        }
    }
    
    // MARK: - AssistantSession Refinement Methods
    
    func processAssistantSessionRefinement(
        sessionId: String,
        audioData: Data,
        modelId: String? = nil,
        streaming: Bool = false
    ) async throws -> HTTPURLResponse {
        
        let url = URL(string: "\(baseURL)/assistant-sessions/\(sessionId)/refine")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        
        if streaming {
            request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        }
        
        // Create multipart form data
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        
        var formData = Data()
        
        // Add audio file
        formData.append("--\(boundary)\r\n".data(using: .utf8)!)
        formData.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"refinement_audio.wav\"\r\n".data(using: .utf8)!)
        formData.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        formData.append(audioData)
        formData.append("\r\n".data(using: .utf8)!)
        
        // Add model ID if provided
        if let modelId = modelId {
            formData.append("--\(boundary)\r\n".data(using: .utf8)!)
            formData.append("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n".data(using: .utf8)!)
            formData.append(modelId.data(using: .utf8)!)
            formData.append("\r\n".data(using: .utf8)!)
        }
        
        formData.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = formData
        
        let (_, response) = try await URLSession.shared.data(for: request)
        return response as! HTTPURLResponse
    }
} 