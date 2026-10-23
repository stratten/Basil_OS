import Foundation
import os

// MARK: - Networking Core Methods for APIClient
extension APIClient {
    // Briefly wait for backend health using exponential backoff up to ~5s
    private func waitBrieflyForHealth(maxWaitSeconds: Int = 5) async {
        var backoffMs = 100
        let deadline = Date().addingTimeInterval(TimeInterval(maxWaitSeconds))
        while Date() < deadline {
            await self.updatePortAndCheckStatus()
            if self.isBackendAvailable { return }
            try? await Task.sleep(nanoseconds: UInt64(backoffMs) * 1_000_000)
            backoffMs = min(backoffMs + 100, 500)
        }
    }

    func get(_ endpoint: String) async throws -> Data {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let url = URL(string: self.baseURL + endpoint)!
        var request = URLRequest(url: url)
        request.timeoutInterval = 30 // Longer timeout for regular requests
        #if DEBUG
        DevLogger.shared.info("📤 GET request to \(endpoint) (full URL: \(url.absoluteString))", context: "APIClient")
        #endif
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            #if DEBUG
            DevLogger.shared.info("📥 GET response from \(endpoint):", context: "APIClient")
            DevLogger.shared.info("  Status: \(String(describing: (response as? HTTPURLResponse)?.statusCode))", context: "APIClient")
            DevLogger.shared.info("  Headers: \(String(describing: (response as? HTTPURLResponse)?.allHeaderFields))", context: "APIClient")
            DevLogger.shared.info("  Data length: \(data.count) bytes", context: "APIClient")
            DevLogger.shared.info("  Content: \(String(data: data, encoding: .utf8) ?? "invalid utf8")", context: "APIClient")
            #endif
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            guard (200...299).contains(httpResponse.statusCode) else {
                throw APIError.serverError(statusCode: httpResponse.statusCode)
            }
            return data
        } catch let error as APIError {
            throw error
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ API Error: \(error.localizedDescription)", context: "APIClient")
            #endif
            throw APIError.connectionFailed(from: error)
        }
    }

    func post<T: Encodable>(_ endpoint: String, _ body: T? = nil) async throws -> OperationResponse {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let url = URL(string: "\(self.baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        if let body = body {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let encodedData = try encoder.encode(body)
            request.httpBody = encodedData
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            logger.debug("📤 POST request to \(endpoint) with body: \(String(data: encodedData, encoding: .utf8) ?? "unable to decode")")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        logger.debug("📥 POST response from \(endpoint): \(String(data: data, encoding: .utf8) ?? "unable to decode")")
        logger.debug("📊 POST Status code: \(httpResponse.statusCode)")
        if httpResponse.statusCode >= 400 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("❌ Server error (\(httpResponse.statusCode)): \(errorMessage)")
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        // Try to parse the actual response from the backend
        if !data.isEmpty {
            do {
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                
                // Try to decode as a direct response first
                if let responseDict = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    let status = responseDict["status"] as? String ?? "success"
                    let details = responseDict["task_id"] as? String ?? responseDict["details"] as? String
                    return OperationResponse(operation: "post", status: status, details: details)
                }
            } catch {
                logger.debug("Could not parse response as JSON, returning success with raw data")
                // If we can't parse it, return the raw response as details
                let rawResponse = String(data: data, encoding: .utf8)
                return OperationResponse(operation: "post", status: "success", details: rawResponse)
            }
        }
        
        return OperationResponse(operation: "post", status: "success")
    }

    func post(_ endpoint: String) async throws -> OperationResponse {
        return try await post(endpoint, EmptyBody())
    }

    func postForData<T: Encodable>(_ endpoint: String, _ body: T? = nil) async throws -> Data {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let url = URL(string: "\(self.baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 180
        if let body = body {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let encodedData = try encoder.encode(body)
            request.httpBody = encodedData
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            #if DEBUG
            DevLogger.shared.debug("📤 POST request to \(endpoint) with body: \(String(data: encodedData, encoding: .utf8) ?? "unable to decode")", context: "APIClient")
            #endif
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        #if DEBUG
        DevLogger.shared.debug("📥 POST response from \(endpoint): \(String(data: data, encoding: .utf8) ?? "unable to decode")", context: "APIClient")
        DevLogger.shared.debug("📊 POST Status code: \(httpResponse.statusCode)", context: "APIClient")
        #endif
        if httpResponse.statusCode >= 400 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            #if DEBUG
            DevLogger.shared.error("❌ Server error (\(httpResponse.statusCode)): \(errorMessage)", context: "APIClient")
            #endif
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        return data
    }

    func postForData(_ endpoint: String) async throws -> Data {
        return try await postForData(endpoint, EmptyBody())
    }

    func put(_ endpoint: String, data requestData: Data) async throws -> Data {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        #if DEBUG
        DevLogger.shared.info("📤 PUT request to \(endpoint)", context: "APIClient")
        #endif
        let url = URL(string: self.baseURL + endpoint)!
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestData
        do {
            #if DEBUG
            DevLogger.shared.info("📦 PUT request body: \(String(data: requestData, encoding: .utf8) ?? "invalid utf8")", context: "APIClient")
            #endif
            let (responseData, response) = try await URLSession.shared.data(for: request)
            #if DEBUG
            DevLogger.shared.info("📥 PUT response from \(endpoint): \(String(data: responseData, encoding: .utf8) ?? "invalid utf8")", context: "APIClient")
            #endif
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            #if DEBUG
            DevLogger.shared.info("📊 PUT Status code: \(httpResponse.statusCode)", context: "APIClient")
            #endif
            guard (200...299).contains(httpResponse.statusCode) else {
                throw APIError.serverError(statusCode: httpResponse.statusCode)
            }
            return responseData
        } catch let error as APIError {
            throw error
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ API Error: \(error.localizedDescription)", context: "APIClient")
            #endif
            throw APIError.connectionFailed(from: error)
        }
    }

    func patch(_ endpoint: String, body requestData: Data) async throws -> Data {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let url = URL(string: self.baseURL + endpoint) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestData
        let (responseData, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        return responseData
    }

    func delete(_ endpoint: String) async throws -> OperationResponse {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let url = URL(string: "\(self.baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        logger.debug("📤 DELETE request to \(endpoint)")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        logger.debug("📥 DELETE response from \(endpoint): \(String(data: data, encoding: .utf8) ?? "unable to decode")")
        logger.debug("📊 DELETE Status code: \(httpResponse.statusCode)")
        if httpResponse.statusCode >= 400 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("❌ Server error (\(httpResponse.statusCode)): \(errorMessage)")
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        return OperationResponse(operation: "delete", status: "success")
    }

    func getSync(_ endpoint: String) throws -> Data {
        guard let url = URL(string: self.baseURL + endpoint) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 5
        var responseData: Data?
        var responseError: Error?
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                responseError = error
            } else if let httpResponse = response as? HTTPURLResponse,
                      !(200...299).contains(httpResponse.statusCode) {
                responseError = APIError.serverError(statusCode: httpResponse.statusCode)
            } else {
                responseData = data
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 5)
        if let error = responseError {
            throw error
        }
        guard let data = responseData else {
            throw APIError.invalidResponse
        }
        return data
    }

    func putSync(_ endpoint: String, data requestData: Data) throws -> Data {
        guard let url = URL(string: self.baseURL + endpoint) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestData
        request.timeoutInterval = 5
        var responseData: Data?
        var responseError: Error?
        let semaphore = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                responseError = error
            } else if let httpResponse = response as? HTTPURLResponse,
                      !(200...299).contains(httpResponse.statusCode) {
                responseError = APIError.serverError(statusCode: httpResponse.statusCode)
            } else {
                responseData = data
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 5)
        if let error = responseError {
            throw error
        }
        guard let data = responseData else {
            throw APIError.invalidResponse
        }
        return data
    }

    /// POST request with raw Data as body
    func post(_ endpoint: String, body: Data) async throws -> Data {
        return try await post(endpoint, body: body, timeout: 120)
    }
    
    /// POST request with raw Data as body and custom timeout
    /// Use longer timeouts for operations that may take a while (e.g., workflow resume)
    func post(_ endpoint: String, body: Data, timeout: TimeInterval) async throws -> Data {
        if !isBackendAvailable { await waitBrieflyForHealth() }
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = timeout
        #if DEBUG
        DevLogger.shared.debug("📤 POST request to \(endpoint) with raw data body: \(body.count) bytes, timeout: \(timeout)s", context: "APIClient")
        #endif
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        #if DEBUG
        DevLogger.shared.debug("📥 POST response from \(endpoint): \(String(data: data, encoding: .utf8) ?? "unable to decode")", context: "APIClient")
        DevLogger.shared.debug("📊 POST Status code: \(httpResponse.statusCode)", context: "APIClient")
        #endif
        if httpResponse.statusCode >= 400 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            #if DEBUG
            DevLogger.shared.error("❌ Server error (\(httpResponse.statusCode)): \(errorMessage)", context: "APIClient")
            #endif
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        return data
    }

    // Private helper
    static func readPortFromFile() -> Int? {
        let fileManager = FileManager.default
        
        // Try multiple possible port file locations
        let bundleId = Bundle.main.bundleIdentifier ?? "com.stratten.basil"
        let appSupportPortPath = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("\(bundleId)/server_port").path
        let possiblePortFilePaths = [
            // 1. Development environment: relative to current directory 
            URL(fileURLWithPath: fileManager.currentDirectoryPath)
                .deletingLastPathComponent()
                .appendingPathComponent(".server_port").path,
            
            // 2. User Application Support (primary)
            appSupportPortPath,
            
            // 3. Legacy location (just in case)
            "\(NSHomeDirectory())/.basil/.server_port"
        ].compactMap { $0 }
        
        #if DEBUG
        print("🔍 Checking for port file in the following locations:")
        for path in possiblePortFilePaths {
            let exists = fileManager.fileExists(atPath: path)
            print("  - \(path) [\(exists ? "EXISTS" : "NOT FOUND")]")
        }
        #endif
        
        // Try each location until we find a valid port file
        for portFilePath in possiblePortFilePaths {
            guard fileManager.fileExists(atPath: portFilePath) else { continue }
            
            do {
                let portString = try String(contentsOfFile: portFilePath, encoding: .utf8)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                
                guard let port = Int(portString) else {
                    #if DEBUG
                    print("⚠️ Port file at \(portFilePath) contains invalid port: '\(portString)'")
                    #endif
                    continue
                }
                
                #if DEBUG
                print("📡 Found valid backend port \(port) in: \(portFilePath)")
                #endif
                return port
                
            } catch {
                #if DEBUG
                print("⚠️ Could not read port file at \(portFilePath): \(error)")
                #endif
                continue
            }
        }
        
        #if DEBUG
        print("⚠️ Could not read port from any location, defaulting to 8000")
        #endif
        return nil
    }
}

// MARK: - Startup Status

/// Response from the startup status endpoint
struct StartupStatusResponse: Codable {
    let message: String
}

extension APIClient {
    func fetchStartupStatus() async throws -> StartupStatusResponse {
        guard isBackendAvailable else {
            DevLogger.shared.warning("Attempted to fetch startup status, but backend is not available.", context: "APIClient")
            throw APIError.backendNotAvailable
        }
        let endpoint = "/api/v1/startup/status"
        
        #if DEBUG
        DevLogger.shared.info("📤 GET request for startup status: \(endpoint)", context: "APIClient")
        #endif
        
        do {
            let data = try await get(endpoint) // Reuses the existing generic get method
            
            #if DEBUG
            let responseString = String(data: data, encoding: .utf8) ?? "Invalid UTF-8 string"
            DevLogger.shared.info("📥 Startup status raw response: \(responseString)", context: "APIClient")
            #endif

            let decoder = JSONDecoder()
            let statusResponse = try decoder.decode(StartupStatusResponse.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ Decoded startup status: '\(statusResponse.message)'", context: "APIClient")
            #endif
            
            return statusResponse
        } catch let error as APIError {
            DevLogger.shared.error("❌ APIError fetching startup status ('(endpoint)'): \(error)", context: "APIClient")
            throw error
        } catch {
            DevLogger.shared.error("❌ Unexpected error fetching startup status ('(endpoint)'): \(error.localizedDescription)", context: "APIClient")
            throw APIError.decodingFailed(error) // Or a more general error
        }
    }
} 