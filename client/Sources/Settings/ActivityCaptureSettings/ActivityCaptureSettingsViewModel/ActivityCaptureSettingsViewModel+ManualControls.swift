import Foundation

extension ActivityCaptureSettingsViewModel {
    // MARK: - Manual Controls
    func performTestCapture() async {
        await triggerTestCapture()
    }
    
    func processBacklog() async {
        await processBacklogNow()
    }
    
    func clearBacklog() async {
        operationInProgress = true
        
        do {
            showOperationMessage("Clearing backlog...")
            
            // Call the clear-backlog endpoint
            let data = try await apiClient.post("/activity-capture/processing/clear-backlog", body: Data())
            
            // Parse response
            let decoder = JSONDecoder()
            
            struct ClearBacklogResponse: Codable {
                let success: Bool
                let message: String
                let data: ClearBacklogData?
                
                struct ClearBacklogData: Codable {
                    let deletedCount: Int
                    let pendingDeleted: Int
                    let ocrCompleteDeleted: Int
                    let failedDeleted: Int
                    
                    enum CodingKeys: String, CodingKey {
                        case deletedCount = "deleted_count"
                        case pendingDeleted = "pending_deleted"
                        case ocrCompleteDeleted = "ocr_complete_deleted"
                        case failedDeleted = "failed_deleted"
                    }
                }
            }
            
            let response = try decoder.decode(ClearBacklogResponse.self, from: data)
            
            if response.success {
                if let responseData = response.data, responseData.deletedCount > 0 {
                    showOperationMessage("Backlog deleted: \(responseData.pendingDeleted) pending, \(responseData.ocrCompleteDeleted) OCR complete, \(responseData.failedDeleted) failed (\(responseData.deletedCount) total)")
                } else {
                    showOperationMessage(response.message)
                }
            } else {
                showOperationMessage("Error: \(response.message)")
            }
            
            // Refresh status after clearing
            await refreshStatus()
            
        } catch {
            showOperationMessage("Error: Failed to clear backlog - \(error.localizedDescription)")
        }
        
        operationInProgress = false
    }
    
    func triggerTestCapture() async {
        operationInProgress = true
        
        do {
            // Use the native WindowCaptureService to perform the actual capture
            let captureResult = await WindowCaptureService.shared.captureActiveWindow()
            
            if captureResult.success, let imagePath = captureResult.imagePath {
                // Send the captured data to backend for processing
                let captureData = [
                    "image_path": imagePath,
                    "app_name": captureResult.appName,
                    "window_title": captureResult.windowTitle,
                    "capture_type": "manual_test"
                ]
                
                let jsonData = try JSONSerialization.data(withJSONObject: captureData)
                _ = try await apiClient.post("/capture/process", body: jsonData)
                
                showOperationMessage("Test capture completed successfully: \(captureResult.appName) - \(captureResult.windowTitle)")
            } else {
                showOperationMessage("Error: \(captureResult.displayError)")
            }
            
            // Refresh stats after capture
            await loadCaptureStats()
            await refreshStatus()
            
        } catch {
            showOperationMessage("Error: Test capture failed - \(error.localizedDescription)")
        }
        
        operationInProgress = false
    }
    
    func processBacklogNow() async {
        operationInProgress = true
        
        do {
            showOperationMessage("Processing backlog...")
            let progress = try await apiClient.startActivityCaptureProcessing()
            processingProgress = progress
            startProcessingProgressPoll()
        } catch {
            showOperationMessage("Error: Failed to process backlog - \(error.localizedDescription)")
        }
        
        operationInProgress = false
    }

    func cancelProcessingBacklog() async {
        isCancelingProcessing = true
        do {
            _ = try await apiClient.cancelActivityCaptureProcessing()
        } catch {
            isCancelingProcessing = false
            showOperationMessage("Error: Failed to cancel processing - \(error.localizedDescription)")
        }
    }

    func startProcessingProgressPoll() {
        processingProgressPollTask?.cancel()
        processingProgressPollTask = Task { [weak self] in
            guard let self else { return }

            while !Task.isCancelled && self.isViewVisible {
                do {
                    let progress = try await self.apiClient.getActivityCaptureProcessingProgress()
                    await MainActor.run {
                        self.processingProgress = progress
                    }
                    await self.refreshStatus()

                    if !progress.active {
                        break
                    }
                } catch {
                    if Task.isCancelled || !self.isViewVisible {
                        break
                    }
                    showOperationMessage("Error: Failed to refresh processing progress - \(error.localizedDescription)")
                    break
                }

                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }

            // The progress readout only represents an in-flight run. Clear it
            // after completion, cancellation, or an unrecoverable poll error.
            await MainActor.run {
                self.isCancelingProcessing = false
                self.processingProgress = nil
            }
        }
    }
}
