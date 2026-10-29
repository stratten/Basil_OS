import SwiftUI

extension ActivityCaptureSettingsViewModel {
    // MARK: - Settings Management
    func loadActivityCaptureSettings() async {
        do {
            let response = try await apiClient.getActivityCaptureSettings()
            
            automaticCaptureEnabled = response.activityCaptureEnabled
            startAtStartup = response.startAtStartup
            excludedBundleIds = response.excludedBundleIds.map {
                AudioAppNameResolver.parentBundleID(from: $0)
            }
            
            // Map backend frequency to valid picker options
            let backendMinutes = Double(response.frequencyMinutes)
            captureFrequencyMinutes = mapToValidFrequency(backendMinutes)
            
            selectedProcessingModel = response.processingModel
            processingMode = response.processingMode == "scheduled" ? .scheduled : .realtime
            processingMaxRecords = response.processingMaxRecords
            
            // Convert time string to Date for DatePicker
            let timeString = response.scheduledProcessingTime
            let timeComponents = timeString.split(separator: ":")
            if timeComponents.count == 2,
               let hour = Int(timeComponents[0]),
               let minute = Int(timeComponents[1]) {
                // Create today's date with the scheduled time
                let calendar = Calendar.current
                let now = Date()
                var components = calendar.dateComponents([.year, .month, .day], from: now)
                components.hour = hour
                components.minute = minute
                components.second = 0
                
                if let scheduledDate = calendar.date(from: components) {
                    scheduledProcessingTime = scheduledDate
                } else {
                    // Fallback if date creation fails
                    scheduledProcessingTime = calendar.date(bySettingHour: hour, minute: minute, second: 0, of: now) ?? now
                }
            } else {
                // Fallback to default time if parsing fails
                let calendar = Calendar.current
                let now = Date()
                scheduledProcessingTime = calendar.date(bySettingHour: 1, minute: 0, second: 0, of: now) ?? now
            }
            
            maxFileAgeDays = response.maxFileAgeDays
            maxStorageMb = response.maxStorageMb
            autoCleanupEnabled = response.autoCleanupEnabled
            idleThresholdSeconds = response.idleThresholdSeconds
            postWakeGraceSeconds = response.postWakeGraceSeconds
            CaptureEligibilityMonitor.shared.applySettings(
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )

        } catch {
            print("Failed to load activity capture settings: \(error)")
        }
    }

    func addExcludedBundleId(_ bundleID: String) async {
        let normalized = AudioAppNameResolver.parentBundleID(from: bundleID)
        guard !normalized.isEmpty, !excludedBundleIds.contains(normalized) else { return }
        await updateExcludedBundleIds(excludedBundleIds + [normalized])
    }

    func removeExcludedBundleId(_ bundleID: String) async {
        let normalized = AudioAppNameResolver.parentBundleID(from: bundleID)
        await updateExcludedBundleIds(excludedBundleIds.filter { $0 != normalized })
    }

    func updateExcludedBundleIds(_ bundleIDs: [String]) async {
        let normalized = uniquePreservingOrder(
            bundleIDs
                .map { AudioAppNameResolver.parentBundleID(from: $0.trimmingCharacters(in: .whitespacesAndNewlines)) }
                .filter { !$0.isEmpty }
        )
        let previous = excludedBundleIds
        excludedBundleIds = normalized
        do {
            let updated = try await apiClient.updateActivityCaptureExcludedBundleIds(normalized)
            excludedBundleIds = updated.excludedBundleIds.map {
                AudioAppNameResolver.parentBundleID(from: $0)
            }
            showOperationMessage("Excluded apps updated.")
        } catch {
            excludedBundleIds = previous
            showOperationMessage("Error: Failed to update excluded apps")
        }
    }

    private func uniquePreservingOrder(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.filter { seen.insert($0).inserted }
    }

    func updateAutomaticCaptureEnabled(_ enabled: Bool) async {
        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: enabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            automaticCaptureEnabled = updatedSettings.activityCaptureEnabled

            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                appDelegate.statusBarManager.updateActivityCaptureEnabledState(
                    updatedSettings.activityCaptureEnabled
                )
            }

            showOperationMessage(
                updatedSettings.activityCaptureEnabled
                    ? "Activity capture enabled - menu item now available"
                    : "Activity capture disabled - menu item hidden"
            )
        } catch {
            showOperationMessage("Error: Failed to update activity capture setting")
            automaticCaptureEnabled = !enabled
        }
    }

    func updateStartAtStartup(_ enabled: Bool) async {
        let previous = startAtStartup
        startAtStartup = enabled
        do {
            let updated = try await apiClient.updateActivityCaptureStartAtStartup(enabled)
            startAtStartup = updated.startAtStartup
            showOperationMessage(
                enabled
                    ? "Activity capture will start automatically on your next launch."
                    : "Activity capture will not start automatically on your next launch."
            )
        } catch {
            startAtStartup = previous
            showOperationMessage("Error: Failed to update startup preference")
        }
    }

    func updateCaptureFrequency(_ minutes: Double) async {
        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: minutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            captureFrequencyMinutes = updatedSettings.frequencyMinutes
            showOperationMessage("Capture frequency updated to \(minutes) minutes")
            
        } catch {
            showOperationMessage("Error: Failed to update capture frequency")
        }
    }
    
    func updateCaptureFrequencyInSeconds(_ seconds: Int) async {
        do {
            // Convert seconds to fractional minutes for backend
            let fractionalMinutes = Double(seconds) / 60.0
            
            // Backend now supports fractional minutes, so send the actual value
            let minutesToSend = fractionalMinutes
            
            _ = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: minutesToSend,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            // Update the UI with the original picker value
            captureFrequencyMinutes = fractionalMinutes
            
            let displayText = seconds < 60 ? "\(seconds) seconds" : "\(seconds / 60) minutes"
            showOperationMessage("Capture frequency updated to \(displayText)")
            
        } catch {
            showOperationMessage("Error: Failed to update capture frequency")
        }
    }
    
    func updateProcessingModel(_ modelId: String) async {
        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: modelId,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            selectedProcessingModel = updatedSettings.processingModel
            showOperationMessage("Processing model updated")
            
        } catch {
            showOperationMessage("Error: Failed to update processing model")
        }
    }
    
    func updateProcessingMode(_ mode: ActivityCaptureProcessingMode) async {
        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: mode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            processingMode = updatedSettings.processingMode == "scheduled" ? .scheduled : .realtime
            showOperationMessage("Processing mode updated")
            
        } catch {
            showOperationMessage("Error: Failed to update processing mode")
        }
    }
    
    func updateScheduledProcessingTime(_ time: Date) async {
        do {
            // Update the local UI state immediately
            scheduledProcessingTime = time
            
            // Convert Date to time string for API
            let timeString = formatTimeString(from: time)
            
            // Save to backend with the time string
            let _ = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: timeString,
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            statusMessage = "Scheduled processing time updated"
            clearStatusMessageAfterDelay()
            
        } catch {
            statusMessage = "Error updating scheduled processing time: \(error.localizedDescription)"
            clearStatusMessageAfterDelay()
        }
    }
    
    func updateAutoCleanupEnabled(_ enabled: Bool) async {
        do {
            _ = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: enabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            
            autoCleanupEnabled = enabled
            showOperationMessage("Auto cleanup \(enabled ? "enabled" : "disabled")")
            
        } catch {
            showOperationMessage("Error: Failed to update auto cleanup setting")
        }
    }
    
    func updateProcessingMaxRecords(_ value: Int) async {
        let clamped = min(max(value, 0), 1000)
        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: clamped,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            processingMaxRecords = updatedSettings.processingMaxRecords
            showOperationMessage("Items per run updated")
        } catch {
            await loadActivityCaptureSettings()
            showOperationMessage("Error: Failed to update items per run")
        }
    }

    func updateIdleThresholdSeconds(_ seconds: Double) async {
        let previous = idleThresholdSeconds
        let normalized = max(seconds, 0)
        idleThresholdSeconds = normalized
        CaptureEligibilityMonitor.shared.applySettings(
            idleThresholdSeconds: normalized,
            postWakeGraceSeconds: postWakeGraceSeconds
        )

        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: normalized,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            idleThresholdSeconds = updatedSettings.idleThresholdSeconds
            CaptureEligibilityMonitor.shared.applySettings(
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            showOperationMessage("Idle capture threshold updated")
        } catch {
            idleThresholdSeconds = previous
            CaptureEligibilityMonitor.shared.applySettings(
                idleThresholdSeconds: previous,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            showOperationMessage("Error: Failed to update idle capture threshold")
        }
    }

    func updatePostWakeGraceSeconds(_ seconds: Double) async {
        let previous = postWakeGraceSeconds
        let normalized = max(seconds, 0)
        postWakeGraceSeconds = normalized
        CaptureEligibilityMonitor.shared.applySettings(
            idleThresholdSeconds: idleThresholdSeconds,
            postWakeGraceSeconds: normalized
        )

        do {
            let updatedSettings = try await apiClient.updateActivityCaptureSettings(
                enabled: automaticCaptureEnabled,
                frequencyMinutes: captureFrequencyMinutes,
                processingModel: selectedProcessingModel,
                processingMode: processingMode.rawValue,
                scheduledProcessingTime: getCurrentScheduledTimeString(),
                processingMaxRecords: processingMaxRecords,
                maxFileAgeDays: maxFileAgeDays,
                maxStorageMb: maxStorageMb,
                autoCleanupEnabled: autoCleanupEnabled,
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: normalized
            )
            postWakeGraceSeconds = updatedSettings.postWakeGraceSeconds
            CaptureEligibilityMonitor.shared.applySettings(
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: postWakeGraceSeconds
            )
            showOperationMessage("Post-wake capture grace updated")
        } catch {
            postWakeGraceSeconds = previous
            CaptureEligibilityMonitor.shared.applySettings(
                idleThresholdSeconds: idleThresholdSeconds,
                postWakeGraceSeconds: previous
            )
            showOperationMessage("Error: Failed to update post-wake capture grace")
        }
    }

    func showOperationMessage(_ message: String) {
        statusMessage = message
        
        // Clear message after 5 seconds
        Task {
            try await Task.sleep(nanoseconds: 5_000_000_000)
            if statusMessage == message {
                statusMessage = nil
            }
        }
    }
    
    func mapToValidFrequency(_ backendMinutes: Double) -> Double {
        // Map backend frequency to closest valid picker option
        let validOptions: [Double] = [0.5, 1.0, 2.0, 5.0, 10.0]
        
        // Find the closest valid option
        let closest = validOptions.min { abs($0 - backendMinutes) < abs($1 - backendMinutes) }
        return closest ?? 5.0 // Default to 5 minutes if no match found
    }
    
    // MARK: - Helper Methods
    // Helper to extract current scheduled time as string
    func getCurrentScheduledTimeString() -> String {
        return formatTimeString(from: scheduledProcessingTime)
    }
    
    // Helper to format Date as HH:MM time string
    func formatTimeString(from date: Date) -> String {
        let calendar = Calendar.current
        let components = calendar.dateComponents([.hour, .minute], from: date)
        let hour = components.hour ?? 1
        let minute = components.minute ?? 0
        return String(format: "%02d:%02d", hour, minute)
    }
    
    func clearStatusMessageAfterDelay() {
        Task {
            try await Task.sleep(nanoseconds: 5_000_000_000) // 5 seconds
            if statusMessage == "Scheduled processing time updated" {
                statusMessage = nil
            }
        }
    }
}

