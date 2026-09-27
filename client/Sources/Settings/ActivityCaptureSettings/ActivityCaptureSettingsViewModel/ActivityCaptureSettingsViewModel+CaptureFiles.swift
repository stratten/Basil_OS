import Foundation

extension ActivityCaptureSettingsViewModel {
    // MARK: - Capture File Management
    func loadCaptureStats() async {
        isLoadingCaptureStats = true
        
        do {
            let response = try await apiClient.fetchCaptureStats()
            
            captureStats = ActivityCaptureStats(
                totalFiles: response.total_files,
                totalSizeBytes: Int64(response.total_size_bytes),
                filesLast7Days: response.files_last_7_days,
                sizeLast7DaysBytes: Int64(response.size_last_7_days_bytes),
                filesLast30Days: response.files_last_30_days,
                sizeLast30DaysBytes: Int64(response.size_last_30_days_bytes)
            )
            
        } catch {
            print("Failed to load capture stats: \(error)")
        }
        
        isLoadingCaptureStats = false
    }
    
    func loadCleanupSettings() async {
        do {
            let response = try await apiClient.fetchCleanupSettings()
            
            retentionDays = response.retention_days
            
            // Convert hour/minute to Date
            var components = DateComponents()
            components.hour = response.cleanup_hour
            components.minute = response.cleanup_minute
            if let time = Calendar.current.date(from: components) {
                cleanupTime = time
            }
            
        } catch {
            print("Failed to load cleanup settings: \(error)")
        }
    }
    
    func updateRetentionDays(_ days: Int) async {
        do {
            let calendar = Calendar.current
            let components = calendar.dateComponents([.hour, .minute], from: cleanupTime)
            
            _ = try await apiClient.updateCleanupSettings(
                autoCleanupEnabled: autoCleanupEnabled,
                retentionDays: days,
                cleanupHour: components.hour,
                cleanupMinute: components.minute
            )
            
            retentionDays = days
            showOperationMessage("Retention period updated to \(days) days")
            
        } catch {
            showOperationMessage("Error: Failed to update retention period")
        }
    }
    
    func updateCleanupTime(_ time: Date) async {
        do {
            let calendar = Calendar.current
            let components = calendar.dateComponents([.hour, .minute], from: time)
            
            _ = try await apiClient.updateCleanupSettings(
                autoCleanupEnabled: autoCleanupEnabled,
                retentionDays: retentionDays,
                cleanupHour: components.hour,
                cleanupMinute: components.minute
            )
            
            cleanupTime = time
            let formatter = DateFormatter()
            formatter.timeStyle = .short
            showOperationMessage("Cleanup time updated to \(formatter.string(from: time))")
            
        } catch {
            showOperationMessage("Error: Failed to update cleanup time")
        }
    }
    
    func updateMaxStorageMb(_ mb: Int) async {
        do {
            _ = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: mb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            maxStorageMb = mb
            showOperationMessage("Maximum storage updated to \(mb) MB")
            
        } catch {
            showOperationMessage("Error: Failed to update maximum storage")
        }
    }
    
    func performCleanup() async {
        operationInProgress = true
        
        do {
            showOperationMessage("Performing cleanup...")
            
            let response = try await apiClient.clearCapturesOlderThan(days: retentionDays)
            showOperationMessage(cleanupResultMessage(prefix: "Cleanup completed", response: response))
            
            await loadCaptureStats()
            
        } catch {
            showOperationMessage("Error: Failed to perform cleanup")
        }
        
        operationInProgress = false
    }
    
    func clearAllCaptures() async {
        do {
            showOperationMessage("Clearing all captures...")
            
            let response = try await apiClient.clearAllCaptures()
            showOperationMessage(cleanupResultMessage(prefix: "All captures cleared", response: response))
            
            await loadCaptureStats()
            
        } catch {
            showOperationMessage("Error: Failed to clear captures")
        }
    }
    
    func clearCapturesOlderThan(days: Int) async {
        do {
            showOperationMessage("Clearing captures older than \(days) days...")
            
            let response = try await apiClient.clearCapturesOlderThan(days: days)
            showOperationMessage(cleanupResultMessage(prefix: "Captures older than \(days) days cleared", response: response))
            
            await loadCaptureStats()
            
        } catch {
            showOperationMessage("Error: Failed to clear old captures")
        }
    }
    
    private func cleanupResultMessage(prefix: String, response: ClearCapturesResponse) -> String {
        if response.status == "partial" {
            let firstError = response.errors?.first ?? "Unknown cleanup error"
            return "Error: \(prefix) partially completed — \(firstError)"
        }
        var parts = [
            "\(prefix): \(response.files_deleted) files deleted",
            formatBytes(Int64(response.space_freed_bytes)) + " freed"
        ]
        if let records = response.records_deleted, records > 0 {
            parts.append("\(records) records deleted")
        }
        if let derived = response.derived_entries_deleted, derived > 0 {
            parts.append("\(derived) derived entries deleted")
        }
        return parts.joined(separator: ", ")
    }

    // MARK: - Utility Methods
    func formatBytes(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
}

