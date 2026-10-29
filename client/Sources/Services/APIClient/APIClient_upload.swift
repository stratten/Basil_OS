import Foundation
import os

// MARK: - File Upload Methods for APIClient
extension APIClient {
    /// Uploads an audio file for transcription
    /// - Parameters:
    ///   - fileURL: Local URL of the audio file to upload
    ///   - language: Language code for transcription (e.g., "en", "auto")
    ///   - description: Optional description of the audio content
    /// - Returns: Data containing the transcription response
    func uploadAudioFile(fileURL: URL, language: String, description: String?) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        guard let url = URL(string: "\(baseURL)/transcribe/file") else {
            throw APIError.invalidURL
        }
        
        // Generate boundary string
        let boundary = "Boundary-\(UUID().uuidString)"
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300  // 5-minute timeout for audio files
        
        // Create multipart form data
        var data = Data()
        
        // Add metadata fields
        data.append("--\(boundary)\r\n".data(using: .utf8)!)
        data.append("Content-Disposition: form-data; name=\"language\"\r\n\r\n".data(using: .utf8)!)
        data.append("\(language)\r\n".data(using: .utf8)!)
        
        if let description = description, !description.isEmpty {
            data.append("--\(boundary)\r\n".data(using: .utf8)!)
            data.append("Content-Disposition: form-data; name=\"description\"\r\n\r\n".data(using: .utf8)!)
            data.append("\(description)\r\n".data(using: .utf8)!)
        }
        
        // Add the file data
        do {
            let fileData = try Data(contentsOf: fileURL)
            let filename = fileURL.lastPathComponent
            let mimeType = mimeTypeForFileExtension(fileURL.pathExtension)
            
            data.append("--\(boundary)\r\n".data(using: .utf8)!)
            data.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
            data.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
            data.append(fileData)
            data.append("\r\n".data(using: .utf8)!)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to read audio file: \(error.localizedDescription)", context: "APIClient")
            #endif
            throw APIError.connectionFailed("Failed to read audio file: \(error.localizedDescription)")
        }
        
        // Add final boundary
        data.append("--\(boundary)--\r\n".data(using: .utf8)!)
        
        // Set request body
        request.httpBody = data
        
        #if DEBUG
        DevLogger.shared.info("📤 Uploading audio file \(fileURL.lastPathComponent) (\(data.count) bytes)", context: "APIClient")
        #endif
        
        // Send the request
        do {
            let (responseData, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            
            #if DEBUG
            DevLogger.shared.info("📥 File upload response status: \(httpResponse.statusCode)", context: "APIClient")
            DevLogger.shared.info("📥 Response data length: \(responseData.count) bytes", context: "APIClient")
            if let responseString = String(data: responseData, encoding: .utf8) {
                DevLogger.shared.info("📥 Response content: \(responseString)", context: "APIClient")
            }
            #endif
            
            if httpResponse.statusCode >= 400 {
                let errorMessage = String(data: responseData, encoding: .utf8) ?? "Unknown error"
                #if DEBUG
                DevLogger.shared.error("❌ Server error (\(httpResponse.statusCode)): \(errorMessage)", context: "APIClient")
                #endif
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
    
    /// Helper method to determine MIME type from file extension
    func mimeTypeForFileExtension(_ extension: String) -> String {
        switch `extension`.lowercased() {
        case "mp3":
            return "audio/mpeg"
        case "wav":
            return "audio/wav"
        case "m4a":
            return "audio/m4a"
        case "aac":
            return "audio/aac"
        case "flac":
            return "audio/flac"
        case "ogg":
            return "audio/ogg"
        default:
            return "application/octet-stream"
        }
    }
} 