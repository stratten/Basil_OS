import Foundation
import os

// MARK: - System Info Response

struct SystemInfoResponse: Codable {
    let totalRamGB: Int
    let isAppleSilicon: Bool
    let gpuAvailable: Bool
    let gpuBackend: String?
    let platform: String
    let machine: String
}

// MARK: - Model Download and Progress Management for APIClient

extension APIClient {

    /// Fetch system hardware info for model compatibility assessment.
    /// Calls `GET /models/system-info` on the backend.
    func getSystemInfo() async throws -> SystemInfoResponse {
        let data = try await get("/models/system-info")
        return try JSONDecoder().decode(SystemInfoResponse.self, from: data)
    }
    // Add a static property to track the last known progress for each model
    static var modelProgressCache: [String: Double] = [:]

    /// Fetch the current download progress for a model
    /// - Parameters:
    ///   - modelType: The model type (e.g., "whisper", "mistral-7b-v03")
    ///   - variant: The variant of the model (e.g., "base", "large-v3")
    /// - Returns: Progress value between 0.0 and 1.0
    func fetchModelDownloadProgress(modelType: String, variant: String) async throws -> Double {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let modelId = "\(modelType)-\(variant)"
        let endpoint = "/models/predefined/\(modelType)/\(variant)/download/progress"
        logger.debug("📤 GET request for model progress: \(endpoint)")
        do {
            let data = try await get(endpoint)
            let decoder = JSONDecoder()
            let response = try decoder.decode([String: Double].self, from: data)
            if let progress = response["progress"] {
                logger.debug("📥 Progress for \(modelType)-\(variant): \(Int(progress * 100))%")
                // Only update cache if new progress is non-zero or greater than current cached value
                if progress > 0 || Self.modelProgressCache[modelId] == nil {
                    Self.modelProgressCache[modelId] = progress
                    #if DEBUG
                        DevLogger.shared.info("Updated progress cache for \(modelId): \(Int(progress * 100))%", context: "APIClient")
                    #endif
                } else {
                    // If server returns 0 but we have a higher cached value, log this discrepancy
                    if let cachedProgress = Self.modelProgressCache[modelId], cachedProgress > progress {
                        #if DEBUG
                            DevLogger.shared.warning("Server returned \(Int(progress * 100))% for \(modelId) but using cached value of \(Int(cachedProgress * 100))%", context: "APIClient")
                        #endif
                        return cachedProgress
                    }
                }
                return progress
            } else {
                logger.warning("⚠️ No progress value found in response")
                // Return cached value if available, otherwise 0
                if let cachedProgress = Self.modelProgressCache[modelId] {
                    #if DEBUG
                        DevLogger.shared.info("Using cached progress for \(modelId): \(Int(cachedProgress * 100))%", context: "APIClient")
                    #endif
                    return cachedProgress
                }
                return 0.0
            }
        } catch {
            logger.error("❌ Failed to fetch progress: \(error.localizedDescription)")
            // Return cached value if available, otherwise rethrow
            if let cachedProgress = Self.modelProgressCache[modelId] {
                #if DEBUG
                    DevLogger.shared.warning("Error fetching progress for \(modelId), using cached value: \(Int(cachedProgress * 100))%", context: "APIClient")
                #endif
                return cachedProgress
            }
            throw error
        }
    }

    /// Fetch the current download progress metadata for a model (full metadata, not just progress value)
    /// - Parameters:
    ///   - modelType: The model type (e.g., "whisper", "mistral-7b-v03")
    ///   - variant: The variant of the model (e.g., "base", "large-v3")
    /// - Returns: Dictionary of progress metadata
    func fetchModelDownloadProgressMetadata(modelType: String, variant: String) async throws -> [String: Any] {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/models/predefined/" + modelType + "/" + variant + "/download/progress"
        // Only log occasionally to reduce log spam
        if arc4random_uniform(5) == 0 {
            logger.debug("📤 GET request for model progress metadata: \(endpoint)")
        }
        let url = URL(string: baseURL + endpoint)!
        var request = URLRequest(url: url)
        // Add keep-alive header to reuse connections
        request.setValue("keep-alive", forHTTPHeaderField: "Connection")
        // Set a shorter timeout for progress requests
        request.timeoutInterval = 5
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            guard (200 ... 299).contains(httpResponse.statusCode) else {
                throw APIError.serverError(statusCode: httpResponse.statusCode)
            }
            let json = try JSONSerialization.jsonObject(with: data, options: [])
            guard let dict = json as? [String: Any] else {
                throw APIError.decodingFailed(NSError(domain: "APIClient", code: 0, userInfo: [NSLocalizedDescriptionKey: "Progress response is not a dictionary"]))
            }
            return dict
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.connectionFailed(from: error)
        }
    }

    // Function to reset progress cache for a model when download completes or is canceled
    func resetProgressCache(modelType: String, variant: String) {
        let modelId = "\(modelType)-\(variant)"
        Self.modelProgressCache.removeValue(forKey: modelId)
        #if DEBUG
            DevLogger.shared.info("Reset progress cache for \(modelId)", context: "APIClient")
        #endif
    }

    func streamModelLogs(_ modelType: String, _ variant: String) -> AsyncStream<String> {
        AsyncStream { continuation in
            let task = Task {
                do {
                    let url = URL(string: baseURL + "/models/predefined/\(modelType)/\(variant)/logs")!
                    let (result, _) = try await URLSession.shared.bytes(from: url)

                    for try await line in result.lines {
                        if line.hasPrefix("data: ") {
                            let jsonStr = String(line.dropFirst(6))
                            if let data = jsonStr.data(using: .utf8),
                               let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                               let logMessage = json["log"]
                            {
                                continuation.yield(logMessage)
                            }
                        }
                    }
                } catch {
                    logger.error("❌ Log streaming error: \(error.localizedDescription)")
                    continuation.finish()
                }
            }

            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }
}
