import AppKit
import Combine

extension AgentTaskResultWidgetController {
    /// Public entry point used by the agentTask hotkey handler when the
    /// user triggers the hotkey while a follow-up-eligible row is the
    /// focused row in the React sidebar. Routes through the same
    /// internal machinery as a JS-bridge-initiated follow-up so there's
    /// only one capture-pipeline path to reason about.
    func startFollowUpCapture(rootTaskId: String) {
        handleFollowUpCaptureStart(
            rootTaskId: rootTaskId,
            previousTaskId: rootTaskId
        )
    }

    func handleFollowUpCaptureStart(rootTaskId: String, previousTaskId: String? = nil) {
        guard followUpCaptureVM == nil else { return }
        let followUpId = UUID().uuidString
        let resolvedPreviousTaskId = previousTaskId ?? rootTaskId
        let captureVM = AgentTaskCaptureViewModel(
            rootTaskId: rootTaskId,
            previousTaskId: resolvedPreviousTaskId
        )
        guard AgentTaskFollowUpCaptureLease.shared.acquire(
            ownerID: followUpCaptureOwnerID,
            onComplete: { [weak captureVM] in captureVM?.completeCapture() },
            onCancel: { [weak captureVM] in captureVM?.cancelCapture() }
        ) else {
            webView?.sendCaptureStateChanged(
                type: "followUp",
                isCapturing: false,
                wordsDetected: "Another task window is recording.",
                audioLevel: 0,
                silenceProgress: 0
            )
            return
        }
        captureVM.preGeneratedAgentTaskId = followUpId
        self.followUpCaptureVM = captureVM
        self.followUpCancellables.removeAll()

        captureVM.onCaptureComplete = { [weak self, weak captureVM] in
            guard let self = self else { return }
            let attachedPaths = captureVM?.referencePaths ?? []
            self.webView?.sendCaptureStateChanged(
                type: "followUp", isCapturing: false,
                wordsDetected: "", audioLevel: 0, silenceProgress: 0
            )
            self.followUpCaptureVM = nil
            self.followUpCancellables.removeAll()
            AgentTaskFollowUpCaptureLease.shared.release(ownerID: self.followUpCaptureOwnerID)

            // Pass the parent linkage explicitly so the React handler
            // doesn't have to rely on a pre-stashed
            // ``pendingFollowUpParent`` to recognize this register-and-
            // select as a follow-up. The hotkey-initiated path goes
            // straight from Swift to here without ever touching React's
            // pre-capture state, so without this argument the React
            // handler falls through to its "register a fresh top-level
            // agent" branch and visually hides the parent card.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.webView?.sendRegisterAndSelectAgent(
                    agentTaskId: followUpId,
                    rootTaskId: rootTaskId,
                    previousTaskId: resolvedPreviousTaskId,
                    referencePaths: attachedPaths
                )
            }
        }
        captureVM.onCaptureCanceled = { [weak self] in
            guard let self else { return }
            self.followUpCaptureVM = nil
            self.followUpCancellables.removeAll()
            AgentTaskFollowUpCaptureLease.shared.release(ownerID: self.followUpCaptureOwnerID)
            self.webView?.sendCaptureStateChanged(
                type: "followUp",
                isCapturing: false,
                wordsDetected: "",
                audioLevel: 0,
                silenceProgress: 0
            )
        }

        // Forward live transcription AND live audio level to the React inline
        // recording bar. CombineLatest re-emits whenever either the word list or
        // the audio level changes, always carrying the latest of both, so one
        // capture-state message never clobbers a field with a stale value. The
        // previous words-only sink hardcoded audioLevel: 0, which is why the web
        // recording bubble never reacted to speech. $audioLevel is already
        // throttled to ~10 Hz at the source (AudioCaptureService
        // .audioLevelUpdateInterval).
        Publishers.CombineLatest(captureVM.$wordsDetected, captureVM.$audioLevel)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] words, level in
                self?.webView?.sendCaptureStateChanged(
                    type: "followUp", isCapturing: true,
                    wordsDetected: words.joined(separator: " "),
                    audioLevel: level, silenceProgress: 0
                )
            }
            .store(in: &followUpCancellables)

        // Files dropped while recording attach to this capture; mirror them so the recording bar can list and remove them.
        if let referenceMirror = webView?.mirrorFollowUpCaptureReferences(of: captureVM) {
            referenceMirror.store(in: &followUpCancellables)
        }

        // Deliberately not subscribed to `captureVM.sizeUpdateRequest`. That publisher sizes the standalone capture panel (160 or 280 points wide) and fires whenever a file is dropped, so honoring it here snapped the whole result widget to the capture panel's size. This recording is the inline bar in the web layout, which has no text mode and lists dropped files itself.

        webView?.sendCaptureStateChanged(
            type: "followUp", isCapturing: true,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )

        captureVM.startCapture()
    }

    func handleFollowUpCaptureStop() {
        followUpCaptureVM?.completeCapture()
    }

    func handleFollowUpCaptureCancel() {
        followUpCaptureVM?.cancelCapture()
        followUpCaptureVM = nil
        followUpCancellables.removeAll()
        AgentTaskFollowUpCaptureLease.shared.release(ownerID: followUpCaptureOwnerID)
        webView?.sendCaptureStateChanged(
            type: "followUp", isCapturing: false,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    func handleRefinementStart() {
        webView?.sendCaptureStateChanged(
            type: "refinement", isCapturing: true,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    func handleRefinementStop() {
        webView?.sendCaptureStateChanged(
            type: "refinement", isCapturing: false,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    /// Called by the hotkey handler when Escape is pressed and an
    /// in-widget follow-up capture is active. Returns true if a capture
    /// was actually canceled.
    @discardableResult
    func cancelActiveFollowUpCapture() -> Bool {
        guard followUpCaptureVM != nil else { return false }
        handleFollowUpCaptureCancel()
        return true
    }

    /// True iff a follow-up audio capture is currently in flight. Read
    /// by the hotkey handler to decide whether to complete vs start.
    var isFollowUpCapturing: Bool {
        followUpCaptureVM?.isCapturing == true
    }

    /// Force-completes an in-flight follow-up capture. Used by the
    /// hotkey "complete capture" path.
    @discardableResult
    func completeActiveFollowUpCapture() -> Bool {
        guard let vm = followUpCaptureVM, vm.isCapturing else { return false }
        vm.completeCapture()
        return true
    }
}
