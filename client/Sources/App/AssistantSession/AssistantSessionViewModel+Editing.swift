import SwiftUI
import Combine
import Foundation

// MARK: - Editing: Edit Mode and Sample Saving
extension AssistantSessionViewModel {
    
    // MARK: - Edit Mode Control
    
    func enterEditMode() {
        guard assistantSessionStatus == .completed else {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Cannot enter edit mode - AssistantSession not completed", context: "AssistantSessionViewModel")
            #endif
            return
        }

        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Entering edit mode - copying assistantOutput (\(assistantOutput.count) chars) to editableContent", context: "AssistantSessionViewModel")
        DevLogger.shared.info("[ASSISTANT_SESSION] First 100 chars of content: \(String(assistantOutput.prefix(100)))", context: "AssistantSessionViewModel")
        #endif

        isEditMode = true
        editableContent = assistantOutput // Copy current output for editing
        
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Edit mode enabled - editableContent now has \(editableContent.count) chars", context: "AssistantSessionViewModel")
        #endif
    }
    
    func cancelEditMode() {
        isEditMode = false
        editableContent = "" // Clear edited content
        
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Canceled edit mode", context: "AssistantSessionViewModel")
        #endif
    }
    
    func applyEdits() {
        assistantOutput = editableContent // Save edits back
        isEditMode = false

        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Applied edits to AssistantSession output", context: "AssistantSessionViewModel")
        #endif
    }
    
    // MARK: - Save as Sample

    func saveAsSample(explicitContent: String? = nil) {
        guard let sessionId = sessionId else {
            #if DEBUG
            DevLogger.shared.error("No session ID available to save sample", context: "AssistantSessionViewModel")
            #endif
            return
        }

        guard !sampleSaved else {
            #if DEBUG
            DevLogger.shared.info("Sample already saved for this session", context: "AssistantSessionViewModel")
            #endif
            return
        }

        savingSample = true

        let contentToSend: String? = {
            if let explicitContent, !explicitContent.isEmpty {
                return explicitContent
            }
            if isEditMode && !editableContent.isEmpty {
                return editableContent
            }
            if !assistantOutput.isEmpty {
                return assistantOutput
            }
            return nil
        }()

        Task {
            do {
                #if DEBUG
                DevLogger.shared.info("Saving AssistantSession as writing sample: \(sessionId)", context: "AssistantSessionViewModel")
                #endif

                guard let url = URL(string: "\(APIClient.shared.baseURL)/assistant-sessions/\(sessionId)/save-sample") else {
                    throw URLError(.badURL)
                }

                var request = URLRequest(url: url)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")

                if let contentToSend {
                    struct SaveSampleRequest: Codable {
                        let content: String
                    }
                    let requestBody = SaveSampleRequest(content: contentToSend)
                    request.httpBody = try JSONEncoder().encode(requestBody)

                    #if DEBUG
                    DevLogger.shared.info("Saving content (\(contentToSend.count) chars)", context: "AssistantSessionViewModel")
                    #endif
                }
                
                let (data, response) = try await URLSession.shared.data(for: request)
                
                guard let httpResponse = response as? HTTPURLResponse else {
                    throw URLError(.badServerResponse)
                }
                
                // Define response structure
                struct SaveSampleResponse: Codable {
                    let status: String
                    let sample_id: String?
                    let context_type: String?
                    let signature_detected: Bool?
                    let contact_tracked: Bool?
                    let error: String?
                    let message: String?
                }
                
                let decodedResponse = try JSONDecoder().decode(SaveSampleResponse.self, from: data)
                
                await MainActor.run {
                    // Only mark as saved if backend confirms success
                    if httpResponse.statusCode == 200 && decodedResponse.status == "saved" {
                        self.sampleSaved = true
                        #if DEBUG
                        DevLogger.shared.info("Successfully saved AssistantSession as writing sample (ID: \(decodedResponse.sample_id ?? "unknown"))", context: "AssistantSessionViewModel")
                        #endif
                    } else {
                        #if DEBUG
                        DevLogger.shared.error("Backend returned error status: \(decodedResponse.error ?? "unknown")", context: "AssistantSessionViewModel")
                        #endif
                    }
                    self.savingSample = false
                }
            } catch {
                await MainActor.run {
                    self.savingSample = false
                }
                
                #if DEBUG
                DevLogger.shared.error("Failed to save AssistantSession as sample: \(error)", context: "AssistantSessionViewModel")
                #endif
            }
        }
    }
}

