import Foundation
import AppKit

final class WebSocketService_AgentTask {
    unowned let parent: WebSocketService
    
    // AgentTask specific message deduplication
    private var processedAgentTaskHashes = Set<String>()
    private let maxProcessedAgentTasks = 50 // Smaller cache for agentTasks specifically
    
    init(parent: WebSocketService) {
        self.parent = parent
    }
    
    /// Wake-word agentTask trigger handler.
    ///
    /// Wake-word and hotkey are functionally equivalent triggers — both
    /// should drive the same four-gate decision tree against the result-
    /// widget singleton and the active capture widget VM. See
    /// ``HotkeyService/handleAgentTaskHotkey()`` in
    /// `HotkeyHandler_AgentTask.swift` for the canonical documentation of
    /// the gates; this implementation must stay in lockstep with it.
    ///
    /// Note on the eventSubject ping at each return: the `.agentTaskStarted`
    /// event is the existing UI notification that "something agentTask-
    /// related is happening right now" — used by other view models to
    /// suppress conflicting hotkeys, log, etc. Every gate that does
    /// observable work fires it; the (rare) no-op path skips it.
    @MainActor
    func handleAgentTaskStarted(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Received agentTask started event (wake-word)", context: "websocket")
        #endif

        // GATE 1: Capture-widget capture in flight → complete.
        if let captureVM = AgentTaskCaptureInputWindowController.activeController?.anyCaptureViewModel,
           captureVM.isCapturing {
            #if DEBUG
            DevLogger.shared.info(
                "[AGENT_TASK wake] ⏹️ Capture-widget recording — completing capture",
                context: "websocket"
            )
            #endif
            captureVM.completeCapture()
            parent.eventSubject.send(.agentTaskStarted)
            return
        }

        // GATE 2: A primary or detached inline follow-up capture is in
        // flight → complete the lease owner, irrespective of its window.
        if AgentTaskFollowUpCaptureLease.shared.completeActiveCapture() {
            #if DEBUG
            DevLogger.shared.info(
                "[AGENT_TASK wake] ⏹️ Follow-up recording — completing lease owner",
                context: "websocket"
            )
            #endif
            parent.eventSubject.send(.agentTaskStarted)
            return
        }

        let blockingAudioOwners = AudioCaptureService.blockingRecordingOwners()
        if !blockingAudioOwners.isEmpty {
            DevLogger.shared.info(
                "[AGENT_TASK wake] Voice capture blocked by active microphone owner(s): \(blockingAudioOwners.joined(separator: ", "))",
                context: "websocket"
            )
            return
        }

        // GATE 3: Route a follow-up to the most recently focused eligible
        // AgentTask presentation (primary or detached).
        if AgentTaskFollowUpFocusRegistry.shared.startFocusedFollowUp() {
            #if DEBUG
            DevLogger.shared.info(
                "[AGENT_TASK wake] Focused AgentTask presentation is follow-up-eligible — starting inline capture",
                context: "websocket"
            )
            #endif
            parent.eventSubject.send(.agentTaskStarted)
            return
        }

        // GATE 4: Default — spawn a fresh capture widget for a new agent task.
        #if DEBUG
        if let singleton = AgentTaskResultWidgetController.shared, singleton.isVisible {
            let focused = singleton.focusedRowState
            DevLogger.shared.info(
                "[AGENT_TASK wake] Result widget visible but no follow-up-eligible focus (agentTaskId=\(focused?.agentTaskId ?? "nil"), supportsFollowUp=\(focused?.supportsFollowUp ?? false), isProcessing=\(focused?.isProcessing ?? false)) — starting new capture",
                context: "websocket"
            )
        } else {
            DevLogger.shared.info(
                "[AGENT_TASK wake] No result widget visible — starting new agentTask capture",
                context: "websocket"
            )
        }
        #endif

        if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
            appDelegate.statusBarManager?.windowCoordinator.showAgentTaskCaptureWidget()
        }

        parent.eventSubject.send(.agentTaskStarted)
    }
    
    @MainActor
    func handleAgentTaskProgress(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Received agentTask progress event", context: "websocket")
        #endif
        
        // Send as proper agentTask progress event
        parent.eventSubject.send(.agentTaskProgress(json))
    }
    
    @MainActor
    func handleAgentTaskResult(json: [String: Any]) {
        // Apply agentTask specific deduplication
        let messageString = String(describing: json)
        let messageHash = String(messageString.hashValue)
        
        if processedAgentTaskHashes.contains(messageHash) {
            #if DEBUG
            DevLogger.shared.info("🔄 Skipping duplicate agentTask result: \(messageHash)", context: "websocket")
            #endif
            return
        }
        
        // Add to processed messages and manage cache size
        processedAgentTaskHashes.insert(messageHash)
        if processedAgentTaskHashes.count > maxProcessedAgentTasks {
            // Remove oldest entries by clearing and keeping recent ones
            let recentMessages = Array(processedAgentTaskHashes.suffix(maxProcessedAgentTasks / 2))
            processedAgentTaskHashes = Set(recentMessages)
        }
        
        #if DEBUG
        DevLogger.shared.info("🎯 Processing agentTask result: \(json)", context: "websocket")
        #endif
        
        // Send as proper agentTask result event
        parent.eventSubject.send(.agentTaskResult(json))
    }
    
    @MainActor
    func handleAgentTaskWordDetected(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🗣️ Received agentTask words detected: \(json)", context: "websocket")
        #endif
        
        // Send word detection event for real-time UI feedback
        parent.eventSubject.send(.agentTaskWordDetected(json))
    }
    
    @MainActor
    func handleAgentTaskSilenceProgress(json: [String: Any]) {
        #if DEBUG
        if let remainingTime = json["data"] as? [String: Any], let remaining = remainingTime["remaining_time"] as? Double {
            DevLogger.shared.info("🤫 AgentTask silence progress: \(String(format: "%.1f", remaining))s remaining", context: "websocket")
        }
        #endif
        
        // Send silence progress event for real-time UI feedback
        parent.eventSubject.send(.agentTaskSilenceProgress(json))
    }
    
    @MainActor
    func handleAgentTaskCaptureComplete(json: [String: Any]) {
        #if DEBUG
        if let data = json["data"] as? [String: Any], let reason = data["reason"] as? String {
            DevLogger.shared.info("✅ AgentTask capture completed: \(reason)", context: "websocket")
        }
        #endif
        
        // Send capture completion event
        parent.eventSubject.send(.agentTaskCaptureComplete(json))
    }
    
    @MainActor
    func handleCaptureRequest(_ json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🎯 Received agentTask capture request from backend", context: "websocket")
        #endif
        
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("❌ AgentTask capture request missing request_id", context: "websocket")
            #endif
            return
        }
        
        let captureType = json["capture_type"] as? String ?? "window_immediate"
        let captureReason = json["capture_reason"] as? String ?? ""

        #if DEBUG
        DevLogger.shared.info("📸 Processing agentTask capture request \(requestId) of type: \(captureType)", context: "websocket")
        #endif

        let capturePolicy = json["capture_policy"] as? [String: Any]
        let rawExcluded = capturePolicy?["excluded_bundle_ids"] as? [String] ?? []
        let excludedBundleIDs = WindowCaptureService.automaticCaptureExcludedBundleIDs(
            captureReason: captureReason,
            rawBundleIDs: rawExcluded
        )

        if captureReason == "automatic activity capture" {
            CaptureEligibilityMonitor.shared.ensureDefaultsLoaded()
            if let ineligibilityReason = CaptureEligibilityMonitor.shared.currentIneligibilityReason() {
                let responseData: [String: Any] = [
                    "request_id": requestId,
                    "timestamp": Int(Date().timeIntervalSince1970 * 1000),
                    "success": false,
                    "policy_skipped": true,
                    "policy_reason": ineligibilityReason,
                    "image_path": NSNull(),
                    "app_name": "Unknown",
                    "window_title": "",
                    "bundle_id": NSNull(),
                    "capture_method": "swift_window_eligibility_gate",
                    "has_image": false
                ]
                #if DEBUG
                DevLogger.shared.info("⏭️ Automatic capture skipped by eligibility gate for request \(requestId): \(ineligibilityReason)", context: "websocket")
                #endif
                Task { @MainActor in
                    await sendCaptureResponse(responseData)
                }
                return
            }
        }

        // Trigger window capture using Swift WindowCaptureService
        Task { @MainActor in
            let captureResult = await WindowCaptureService.shared.captureActiveWindow(
                excludedBundleIDs: excludedBundleIDs
            )

            var responseData: [String: Any] = [
                "request_id": requestId,
                "timestamp": Int(Date().timeIntervalSince1970 * 1000)
            ]

            if captureResult.policySkipped {
                responseData.merge([
                    "success": false,
                    "policy_skipped": true,
                    "policy_reason": captureResult.error ?? "excluded_app",
                    "image_path": NSNull(),
                    "app_name": captureResult.appName,
                    "window_title": "",
                    "bundle_id": captureResult.bundleIdentifier ?? NSNull(),
                    "capture_method": "swift_window_policy",
                    "has_image": false
                ]) { _, new in new }

                #if DEBUG
                DevLogger.shared.info("⏭️ Automatic capture skipped by policy for request \(requestId): \(captureResult.appName)", context: "websocket")
                #endif
            } else if captureResult.success, let imagePath = captureResult.imagePath {
                // Success case
                responseData["success"] = true
                responseData["image_path"] = imagePath
                responseData["app_name"] = captureResult.appName
                responseData["window_title"] = captureResult.windowTitle
                if let bundleID = captureResult.bundleIdentifier {
                    responseData["bundle_id"] = bundleID
                }
                responseData["perceptual_hash"] = captureResult.perceptualHash ?? NSNull()
                responseData["capture_method"] = "swift_window_service"
                responseData["has_image"] = true

            #if DEBUG
            DevLogger.shared.info("✅ AgentTask capture successful for request \(requestId): \(imagePath)", context: "websocket")
            DevLogger.shared.info("📱 App: \(captureResult.appName) - Window: \(captureResult.windowTitle)", context: "websocket")
            #endif
            } else {
                // Failure case
                responseData.merge([
                    "success": false,
                    "image_path": NSNull(),
                    "app_name": captureResult.appName.isEmpty ? "Unknown" : captureResult.appName,
                    "window_title": captureResult.windowTitle.isEmpty ? "Unknown" : captureResult.windowTitle,
                    "capture_method": "swift_window_service_failed",
                    "has_image": false,
                    "error": captureResult.error ?? "Unknown capture error"
                ]) { _, new in new }
                
                #if DEBUG
                DevLogger.shared.error("❌ AgentTask capture failed for request \(requestId): \(captureResult.error ?? "Unknown error")", context: "websocket")
                #endif
            }
            
            // Send response back to backend
            await sendCaptureResponse(responseData)
        }
    }
    
    @MainActor
    func sendCaptureResponse(_ responseData: [String: Any]) async {
        do {
            let apiBase = APIClient.shared.baseURL
            guard let url = URL(string: "\(apiBase)/capture/capture-response") else {
                #if DEBUG
                DevLogger.shared.error("❌ Invalid agentTask capture response URL", context: "websocket")
                #endif
                return
            }
            
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 10.0
            
            let requestBody = try JSONSerialization.data(withJSONObject: responseData)
            request.httpBody = requestBody
            
            #if DEBUG
            DevLogger.shared.info("📤 Sending agentTask capture response to backend: \(responseData["request_id"] ?? "unknown")", context: "websocket")
            #endif
            
            let (_, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode == 200 {
                    #if DEBUG
                    DevLogger.shared.info("✅ AgentTask capture response sent successfully", context: "websocket")
                    #endif
                } else {
                    #if DEBUG
                    DevLogger.shared.error("❌ AgentTask capture response failed with status: \(httpResponse.statusCode)", context: "websocket")
                    #endif
                }
            }
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to send agentTask capture response: \(error)", context: "websocket")
            #endif
        }
    }

    @MainActor
    func handleWebSocketMessage(_ json: [String: Any]) {
        #if DEBUG
        let incomingEventType = (json["event_type"] as? String) ?? (json["type"] as? String) ?? "unknown"
        DevLogger.shared.info("[WS VOICE] received event_type=\(incomingEventType)", context: "websocket")
        #endif
        if let eventType = json["event_type"] as? String {
            switch eventType {
            case "workflow_plan_ready":
                handleWorkflowPlanReady(json: json)
            case "step_progress_update":
                handleStepProgressUpdate(json: json)
            case "dynamic_step_added":
                handleDynamicStepAdded(json: json)
            case "dynamic_step_updated":
                handleDynamicStepUpdated(json: json)
            case "agent_progress_update":
                handleAgentProgressUpdate(json: json)
            case "collaborative_checkpoint_request":
                handleCollaborativeCheckpointRequest(json: json)
            case "checkpoint_waiting":
                handleCheckpointWaiting(json: json)
            case "checkpoint_resumed":
                handleCheckpointResumed(json: json)
            case "session_context_info":
                handleSessionContextInfo(json: json)
            case "execution_approval_request":
                handleExecutionApprovalRequest(json: json)
            case "capture_request":
                handleCaptureRequest(json)
            default:
                #if DEBUG
                DevLogger.shared.warning("Unknown agentTask event_type: \(eventType)", context: "websocket")
                #endif
            }
        }
    }
    
    @MainActor
    func handleAgentTaskStreaming(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🔄 Received agentTask streaming event: \(json)", context: "websocket")
        #endif
        
        // Extract streaming data
        let operation = json["operation"] as? String ?? "unknown"
        let token = json["token"] as? String ?? ""
        let partialResult = json["partial_result"] as? String ?? ""
        let stage = json["stage"] as? String ?? "generating"
        
        #if DEBUG
        DevLogger.shared.info("🔄 Streaming - Operation: \(operation), Token: '\(token)', Stage: \(stage)", context: "websocket")
        #endif
        
        // Create a streaming progress event with the token data
        let streamingData = [
            "operation": operation,
            "token": token,
            "partial_result": partialResult,
            "stage": stage,
            "streaming": true
        ] as [String : Any]
        
        // Send as agentTask progress to be handled by existing UI
        parent.eventSubject.send(.agentTaskProgress(streamingData))
    }
    
    @MainActor
    func handleAgentTaskStreamingComplete(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("✅ Received agentTask streaming complete event: \(json)", context: "websocket")
        #endif
        
        // Extract completion data
        let operation = json["operation"] as? String ?? "unknown"
        let finalResult = json["final_result"] as? String ?? ""
        
        #if DEBUG
        DevLogger.shared.info("✅ Streaming Complete - Operation: \(operation), Result length: \(finalResult.count)", context: "websocket")
        #endif
        
        // Create a result event with the final data
        let resultData = [
            "operation": operation,
            "success": true,
            "result": finalResult,
            "message": finalResult,
            "streaming_complete": true
        ] as [String : Any]
        
        // Send as agentTask result to complete the operation
        parent.eventSubject.send(.agentTaskResult(resultData))
    }
    
    @MainActor
    func handleWorkflowPlanReady(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("📋 Received workflow plan ready event: \(json)", context: "websocket")
        #endif
        
        let agentTaskId = json["agent_task_id"] as? String ?? ""
        let todoCount = json["todo_count"] as? Int ?? 0
        
        // Create workflow plan ready event
        let workflowData = [
            "agent_task_id": agentTaskId,
            "todo_count": todoCount,
            "event_type": "workflow_plan_ready"
        ] as [String : Any]
        
        parent.eventSubject.send(.workflowPlanReady(workflowData))
    }
    
    @MainActor
    func handleStepProgressUpdate(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🔧 Received step progress update: \(json)", context: "websocket")
        #endif
        
        let todoId = json["todo_id"] as? String ?? ""
        let stepId = json["step_id"] as? String ?? ""
        let status = json["status"] as? String ?? ""
        let resultSummary = json["result_summary"] as? String
        
        // Create step progress event  
        let stepData = [
            "todo_id": todoId,
            "step_id": stepId,
            "status": status,
            "result_summary": resultSummary ?? ""
        ] as [String : Any]
        
        parent.eventSubject.send(.stepProgressUpdate(stepData))
    }
    
    @MainActor
    func handleDynamicStepAdded(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🔧 Received dynamic step added: \(json)", context: "websocket")
        #endif
        // NOTE: Do NOT call showAgentTaskCaptureWidget() here. The capture
        // window controller exists strictly to capture *new* user input
        // (see AgentTaskCaptureWindowController's header doc); progress for
        // an already-running agent is owned by the result-widget
        // singleton, which subscribes to the .dynamicStepAdded event
        // dispatched below. Re-opening the capture widget on a progress
        // event spawns spurious capture panels whenever the original
        // capture has already closed (which is the normal lifecycle —
        // it hands off to the result widget ~0.1s after submit).

        let todoId = json["todo_id"] as? String ?? ""
        let stepId = json["step_id"] as? String ?? ""
        let description = json["description"] as? String ?? ""
        let status = json["status"] as? String ?? "in_progress"
        let executionMethod = json["execution_method"] as? String ?? "dynamic_agent"
        
        // Create dynamic step added event
        let stepData = [
            "todo_id": todoId,
            "step_id": stepId,
            "description": description,
            "status": status,
            "execution_method": executionMethod
        ] as [String : Any]
        
        DevLogger.shared.info("📤 Dispatching dynamicStepAdded to ViewModel", context: "websocket")
        parent.eventSubject.send(.dynamicStepAdded(stepData))
    }
    
    @MainActor
    func handleDynamicStepUpdated(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🔧 Received dynamic step updated: \(json)", context: "websocket")
        #endif
        // NOTE: Do NOT call showAgentTaskCaptureWidget() here. See the
        // matching comment in handleDynamicStepAdded above for the full
        // rationale — in short, the capture widget is for new user
        // input, not progress display, and re-opening it on a step
        // update spawns spurious capture panels after the original
        // capture has handed off to the result-widget singleton.

        let todoId = json["todo_id"] as? String ?? ""
        let description = json["description"] as? String ?? ""
        let status = json["status"] as? String ?? "completed"
        let completionMessage = json["completion_message"] as? String
        let executionMethod = json["execution_method"] as? String ?? "dynamic_agent"
        
        // Create dynamic step updated event
        let stepData = [
            "todo_id": todoId,
            "description": description,
            "status": status,
            "completion_message": completionMessage ?? "",
            "execution_method": executionMethod
        ] as [String : Any]
        
        DevLogger.shared.info("📤 Dispatching dynamicStepUpdated to ViewModel", context: "websocket")
        parent.eventSubject.send(.dynamicStepUpdated(stepData))
    }
    
    @MainActor
    func handleAgentProgressUpdate(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🤖 Received agent progress update: \(json)", context: "websocket")
        #endif
        
        let message = json["message"] as? String ?? ""
        let details = json["details"] as? String
        let executionMethod = json["execution_method"] as? String ?? "dynamic_agent"
        
        // Create agent progress event
        let progressData = [
            "message": message,
            "details": details ?? "",
            "execution_method": executionMethod
        ] as [String : Any]
        
        parent.eventSubject.send(.agentProgressUpdate(progressData))
    }
    
    // MARK: - Collaborative Workflow & Checkpoint Handlers (Phase 3)
    
    @MainActor
    func handleCollaborativeCheckpointRequest(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🛑 Received collaborative checkpoint request: \(json)", context: "websocket")
        #endif
        
        // Forward the complete checkpoint data to the event system
        parent.eventSubject.send(.collaborativeCheckpointRequest(json))
    }
    
    @MainActor
    func handleCheckpointWaiting(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("⏸️ Received checkpoint waiting status: \(json)", context: "websocket")
        #endif
        
        // Forward checkpoint waiting status
        parent.eventSubject.send(.checkpointWaiting(json))
    }
    
    @MainActor
    func handleCheckpointResumed(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("▶️ Received checkpoint resumed status: \(json)", context: "websocket")
        #endif
        
        // Forward checkpoint resumed status
        parent.eventSubject.send(.checkpointResumed(json))
    }
    
    @MainActor
    func handleSessionContextInfo(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("📚 Received session context info: \(json)", context: "websocket")
        #endif
        
        // Forward session context information
        parent.eventSubject.send(.sessionContextInfo(json))
    }
    
    // MARK: - Command Approval Handlers
    
    @MainActor
    func handleExecutionApprovalRequest(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("🔐 Received command approval request: \(json)", context: "websocket")
        #endif
        
        // Extract approval request data
        guard let approvalId = json["approval_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("❌ Command approval request missing approval_id", context: "websocket")
            #endif
            return
        }
        
        guard let command = json["command"] as? String else {
            #if DEBUG
            DevLogger.shared.error("❌ Command approval request missing command", context: "websocket")
            #endif
            return
        }
        
        // Extract optional fields for validation (values forwarded in json to downstream handler)
        let _ = json["full_command"] as? String ?? command
        let _ = json["show_remember"] as? Bool ?? true
        
        #if DEBUG
        DevLogger.shared.info("🔐 Processing approval request \(approvalId) for command: \(command)", context: "websocket")
        #endif
        
        // Forward complete command approval request to be handled by the result view model
        parent.eventSubject.send(.executionApprovalRequest(json))
    }
} 