import SwiftUI

extension TranscriptionWidgetViewModel {
    func toggleRecording() async {
        switch recordingLifecycle {
        case .starting:
            cancelRecordingStartup()
        case .recording:
            stopRecording()
        case .idle, .failed:
            await startRecording()
        case .processing:
            break
        }
    }

    func startRecording() async {
        #if DEBUG
        DevLogger.shared.info("Starting recording - Current text: \"\(transcriptionText)\"", context: "recording_state")
        #endif
        guard isConnected else {
            #if DEBUG
            DevLogger.shared.warning("Cannot start recording - not connected", context: "recording_state")
            #endif
            error = "Cannot start recording - waiting for connection"
            return
        }
        guard recordingLifecycle == .idle || recordingLifecycle == .failed else { return }

        error = nil
        transcriptionText = "Starting microphone..."
        pulseScale = 1.0
        transitionRecordingLifecycle(to: .starting)

        let startupID = UUID()
        activeRecordingStartupID = startupID
        let startupTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performRecordingStartup(startupID: startupID)
        }
        recordingStartupTask = startupTask
        recordingStartupWatchdogTask?.cancel()
        recordingStartupWatchdogTask = Task { @MainActor [weak self] in
            do {
                try await Task.sleep(nanoseconds: Self.recordingStartupTimeoutNanoseconds)
                self?.handleRecordingStartupTimeout(startupID: startupID)
            } catch {
                return
            }
        }
        await startupTask.value
        if activeRecordingStartupID == startupID {
            recordingStartupTask = nil
        }
    }

    func performRecordingStartup(startupID: UUID) async {
        do {
            let activeAppInfo = getActiveApplicationInfo()
            #if DEBUG
            DevLogger.shared.info("Active application: \(activeAppInfo.appName ?? "Unknown"), Window: \(activeAppInfo.windowTitle ?? "Unknown")", context: "recording_state")
            #endif
            audioCaptureController.setContextInfo(
                appName: activeAppInfo.appName,
                windowTitle: activeAppInfo.windowTitle,
                taskCategory: nil
            )
            try await audioCaptureController.startRecording(flowContext: "transcription")
            try Task.checkCancellation()
            guard activeRecordingStartupID == startupID,
                  recordingLifecycle == .starting else {
                audioCaptureController.stopRecording(sendAudioData: false, flowContext: nil, context: nil)
                return
            }
            activeRecordingStartupID = nil
            recordingStartupWatchdogTask?.cancel()
            recordingStartupWatchdogTask = nil
            recordingStartupTask = nil
            transcriptionText = "Recording in progress..."
            pulseScale = 1.5
            transitionRecordingLifecycle(to: .recording)
            #if DEBUG
            DevLogger.shared.info("Recording started successfully", context: "recording_state")
            #endif
        } catch is CancellationError {
            guard activeRecordingStartupID == startupID else { return }
            completeSilentRecordingStartupCancellation()
        } catch {
            guard activeRecordingStartupID == startupID else { return }
            activeRecordingStartupID = nil
            recordingStartupWatchdogTask?.cancel()
            recordingStartupWatchdogTask = nil
            recordingStartupTask = nil
            #if DEBUG
            DevLogger.shared.error("Failed to start recording: \(error)", context: "recording_state")
            #endif
            self.error = error.localizedDescription
            pulseScale = 1.0
            transcriptionText = "Ready to record"
            transitionRecordingLifecycle(to: .failed)
        }
    }

    func cancelRecordingStartup() {
        let hadPendingAutoStart = pendingAutoStartRecording
        pendingAutoStartRecording = false
        guard recordingLifecycle == .starting else {
            if hadPendingAutoStart {
                error = nil
            }
            return
        }
        activeRecordingStartupID = nil
        recordingStartupTask?.cancel()
        recordingStartupTask = nil
        recordingStartupWatchdogTask?.cancel()
        recordingStartupWatchdogTask = nil
        audioCaptureController.cancelRecordingStartup()
        completeSilentRecordingStartupCancellation()
    }

    func handleRecordingStartupTimeout(startupID: UUID) {
        guard activeRecordingStartupID == startupID,
              recordingLifecycle == .starting else { return }
        activeRecordingStartupID = nil
        recordingStartupTask?.cancel()
        recordingStartupTask = nil
        recordingStartupWatchdogTask = nil
        audioCaptureController.cancelRecordingStartup()
        error = "Microphone recording did not start in time."
        pulseScale = 1.0
        transcriptionText = "Ready to record"
        transitionRecordingLifecycle(to: .failed)
    }

    func completeSilentRecordingStartupCancellation() {
        activeRecordingStartupID = nil
        recordingStartupWatchdogTask?.cancel()
        recordingStartupWatchdogTask = nil
        recordingStartupTask = nil
        error = nil
        pulseScale = 1.0
        transcriptionText = "Ready to record"
        transitionRecordingLifecycle(to: .idle)
    }

    func getActiveApplicationInfo() -> (appName: String?, windowTitle: String?) {
        var appName: String? = nil
        var windowTitle: String? = nil
        if let workspace = NSWorkspace.shared.frontmostApplication {
            appName = workspace.localizedName
            let appPID = workspace.processIdentifier
            let options = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
            let windowsListInfo = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]]
            if let windowsListInfo = windowsListInfo {
                for windowInfo in windowsListInfo {
                    if let windowPID = windowInfo[kCGWindowOwnerPID as String] as? Int,
                       windowPID == appPID,
                       let title = windowInfo[kCGWindowName as String] as? String,
                       !title.isEmpty {
                        windowTitle = title
                        break
                    }
                }
            }
        }
        return (appName, windowTitle)
    }

    func stopRecording() {
        if preventRecordingStop {
            #if DEBUG
            DevLogger.shared.info("Recording stop prevented by UI transition", context: "recording_state")
            #endif
            return
        }
        guard recordingLifecycle == .recording else {
            #if DEBUG
            DevLogger.shared.warning("stopRecording called but not recording", context: "AudioCapture")
            #endif
            return
        }
        #if DEBUG
        DevLogger.shared.info("Stopping recording - Current text: \(transcriptionText)", context: "recording_state")
        #endif
        guard audioCaptureController.hasCapturedAudioData else {
            audioCaptureController.stopRecording(sendAudioData: false, flowContext: nil, context: nil)
            elapsedSeconds = 0
            updateAudioLevel(0.0)
            pulseScale = 1.0
            error = "No audio was captured. Try recording again."
            transcriptionText = "No audio captured"
            transitionRecordingLifecycle(to: .failed)
            return
        }
        transitionRecordingLifecycle(to: .processing)
        elapsedSeconds = 0
        updateAudioLevel(0.0)
        transcriptionText = "Processing transcription..."
        #if DEBUG
        DevLogger.shared.info("Recording stopped, text set to processing state", context: "text_state")
        #endif
        if timerCancellable != nil {
            timerCancellable?.cancel()
            timerCancellable = nil
        }
        audioCaptureController.stopRecording(sendAudioData: true, flowContext: nil, context: nil)
    }

    func cancelRecording() async {
        if recordingLifecycle == .starting {
            cancelRecordingStartup()
            return
        }
        guard recordingLifecycle == .recording else { return }
        #if DEBUG
        DevLogger.shared.info("Canceling recording without processing transcription", context: "recording_state")
        #endif
        let settings = APIClient.shared.getCachedTranscriptionSettings()
        let shouldAutoClose = settings.autoCloseOnPaste
        #if DEBUG
        DevLogger.shared.info("Cancel recording - Auto-close preference: \(shouldAutoClose)", context: "recording_state")
        #endif
        transitionRecordingLifecycle(to: .idle)
        if timerCancellable != nil {
            timerCancellable?.cancel()
            timerCancellable = nil
        }
        audioCaptureController.stopRecording(sendAudioData: false, flowContext: nil, context: nil)
        elapsedSeconds = 0
        updateAudioLevel(0.0)
        pulseScale = 1.0
        transcriptionText = "Recording canceled"
        #if DEBUG
        DevLogger.shared.info("Recording canceled, audio data will NOT be sent to server", context: "recording_state")
        #endif
        webSocketService.eventSubject.send(.transcriptionCanceled)
        if shouldAutoClose {
            #if DEBUG
            DevLogger.shared.info("Auto-close is enabled, will close widget after delay", context: "auto_close")
            #endif
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                #if DEBUG
                DevLogger.shared.info("Posting close request due to auto-close preference after cancellation", context: "auto_close")
                #endif
                NotificationCenter.default.post(
                    name: NSNotification.Name("CloseTranscriptionWidgetRequest"),
                    object: nil,
                    userInfo: ["reason": "recording canceled"]
                )
            }
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                self?.transcriptionText = "Ready to record"
            }
        }
    }
}
