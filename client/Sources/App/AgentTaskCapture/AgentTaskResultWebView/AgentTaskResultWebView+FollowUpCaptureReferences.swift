import Combine
import Foundation

extension AgentTaskResultWebView {
    /// Makes files dropped on this window attach to the follow-up recording in progress, and lets the web layer remove one before it is sent.
    ///
    /// Without this a drop during an audio follow-up reached only the text follow-up box, whose files the audio request never reads. `activeCapture` is read at drop time, so the host wires this once and a recording that starts or ends later is picked up without rewiring.
    func routeFileDropsToFollowUpCapture(activeCapture: @escaping () -> AgentTaskCaptureViewModel?) {
        followUpCaptureDropSink = { paths in
            guard let capture = activeCapture(), capture.isCapturing, !capture.hasCompleted else { return false }
            capture.addReferencePaths(paths.map { URL(fileURLWithPath: $0) })
            return true
        }
        onRemoveFollowUpCaptureReference = { index in
            guard let capture = activeCapture(), capture.isCapturing, !capture.hasCompleted else { return }
            capture.removeReferencePath(at: index)
        }
    }

    /// Mirrors the recording's reference files to the web layer, starting with the current list so a new recording clears any list left from the last one.
    func mirrorFollowUpCaptureReferences(of capture: AgentTaskCaptureViewModel) -> AnyCancellable {
        capture.$referencePaths
            .receive(on: DispatchQueue.main)
            .sink { [weak self] urls in
                self?.callJS("window.basilAgentTask.onFollowUpCaptureReferencesChanged", args: urls.map { $0.path })
            }
    }
}
