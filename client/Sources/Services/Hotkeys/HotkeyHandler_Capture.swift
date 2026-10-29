import Foundation
import AppKit

extension HotkeyService {
    @MainActor
    func handleCaptureHotkey() async {
        do {
            let requestUUID = UUID().uuidString
            #if DEBUG
            DevLogger.shared.info("\n=== CAPTURE HOTKEY PRESSED ===", context: "HotkeyService")
            DevLogger.shared.info("📅 Timestamp: \(Date())", context: "HotkeyService")
            DevLogger.shared.info("🔑 Request ID: \(requestUUID)", context: "HotkeyService")
            DevLogger.shared.info("🔍 Starting capture process...", context: "HotkeyService")
            #endif
            
            // Use the Swift WindowCaptureService to capture locally
            #if DEBUG
            DevLogger.shared.info("📸 Using Swift WindowCaptureService for capture...", context: "HotkeyService")
            #endif
            
            let captureResult = await WindowCaptureService.shared.captureActiveWindow()
            
            if !captureResult.success {
                #if DEBUG
                DevLogger.shared.error("❌ Window capture failed: \(captureResult.error ?? "Unknown error")", context: "HotkeyService")
                #endif
                return
            }
            
            guard let imagePath = captureResult.imagePath else {
                #if DEBUG
                DevLogger.shared.error("❌ No image path returned from capture", context: "HotkeyService")
                #endif
                return
            }
            
            #if DEBUG
            DevLogger.shared.info("✅ Window captured successfully", context: "HotkeyService")
            DevLogger.shared.info("📱 App: \(captureResult.appName)", context: "HotkeyService")
            DevLogger.shared.info("🪟 Window: \(captureResult.windowTitle)", context: "HotkeyService")
            DevLogger.shared.info("📸 Image: \(imagePath)", context: "HotkeyService")
            #endif
            
            // Send the captured image path to backend for processing
            #if DEBUG
            DevLogger.shared.info("📤 Sending captured image to backend for processing...", context: "HotkeyService")
            #endif
            
            let startTime = Date().timeIntervalSince1970
            
            // Create request body with image path
            struct CaptureProcessRequest: Encodable {
                let image_path: String
                let app_name: String
                let window_title: String
            }
            
            let requestBody = CaptureProcessRequest(
                image_path: imagePath,
                app_name: captureResult.appName,
                window_title: captureResult.windowTitle
            )
            
            guard let url = URL(string: "\(apiClient.baseURL)/capture/process") else {
                #if DEBUG
                DevLogger.shared.error("❌ Invalid URL for capture process endpoint", context: "HotkeyService")
                #endif
                return
            }
            
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(requestBody)
            request.timeoutInterval = 120 // Extended timeout for processing
            
            #if DEBUG
            DevLogger.shared.info("⏱️ Using extended timeout of 120 seconds for processing", context: "HotkeyService")
            DevLogger.shared.info("🔄 Request ID: \(requestUUID) - Starting process request", context: "HotkeyService")
            #endif
            
            let (data, urlResponse) = try await URLSession.shared.data(for: request)
            
            #if DEBUG
            DevLogger.shared.info("📥 Request ID: \(requestUUID) - Received response", context: "HotkeyService")
            
            if let httpResponse = urlResponse as? HTTPURLResponse {
                DevLogger.shared.info("🔢 HTTP Status: \(httpResponse.statusCode)", context: "HotkeyService")
            }
            
            if let responseString = String(data: data, encoding: .utf8) {
                DevLogger.shared.info("📤 Raw response: \(responseString)", context: "HotkeyService")
            }
            #endif
            
            let endTime = Date().timeIntervalSince1970
            let elapsedTime = (endTime - startTime) * 1000 // Convert to milliseconds
            
            #if DEBUG
            DevLogger.shared.info("✅ Request ID: \(requestUUID) - Processing completed in \(Int(elapsedTime))ms", context: "HotkeyService")
            DevLogger.shared.info("=== CAPTURE HANDLING COMPLETE [\(requestUUID)] ===\n", context: "HotkeyService")
            #endif
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to handle capture hotkey: \(error)", context: "HotkeyService")
            DevLogger.shared.error("⚠️ Error details: \(error.localizedDescription)", context: "HotkeyService")
            
            if let urlError = error as? URLError {
                DevLogger.shared.error("🔍 URL Error code: \(urlError.code.rawValue)", context: "HotkeyService")
                DevLogger.shared.error("🔍 URL Error description: \(urlError.localizedDescription)", context: "HotkeyService")
                
                if urlError.code == .timedOut {
                    DevLogger.shared.error("⏱️ Request timed out. Consider increasing the timeout interval.", context: "HotkeyService")
                }
            }
            
            // Try to determine if this is a decoding error
            if let decodingError = error as? DecodingError {
                switch decodingError {
                case .keyNotFound(let key, let context):
                    DevLogger.shared.error("🔑 Missing key: \(key.stringValue) in: \(context.codingPath.map { $0.stringValue })", context: "HotkeyService")
                case .typeMismatch(let type, let context):
                    DevLogger.shared.error("📋 Type mismatch: expected \(type) at: \(context.codingPath.map { $0.stringValue })", context: "HotkeyService")
                case .valueNotFound(let type, let context):
                    DevLogger.shared.error("🔍 Missing value: expected \(type) at: \(context.codingPath.map { $0.stringValue })", context: "HotkeyService")
                default:
                    DevLogger.shared.error("📋 Decoding error: \(decodingError)", context: "HotkeyService")
                }
            }
            #endif
        }
    }
} 