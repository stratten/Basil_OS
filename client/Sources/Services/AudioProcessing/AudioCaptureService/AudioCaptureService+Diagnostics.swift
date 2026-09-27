import AVFoundation
import Foundation

extension AudioCaptureService {
    func logAudioEngineDiagnostics(context: String) {
        guard let engine = audioEngine else {
            #if DEBUG
                DevLogger.shared.info("[AUDIO DIAG] Engine is nil (", context: context)
            #endif
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            let diagnostics = await audioEngineOperationQueue.diagnostics(for: engine)
            allEnginePointers.insert(diagnostics.enginePointer)
            #if DEBUG
            DevLogger.shared.info("[AUDIO DIAG] Engine Active: \(diagnostics.engineActive ? "YES" : "NO")", context: context)
            DevLogger.shared.info("[AUDIO DIAG] Input Node Active: \(diagnostics.nodeActive ? "YES" : "NO")", context: context)
            DevLogger.shared.info("[AUDIO DIAG] Node Connected: \(diagnostics.nodeConnected ? "YES" : "NO")", context: context)
            DevLogger.shared.info("[AUDIO DIAG] Engine Ptr: \(diagnostics.enginePointer)", context: context)
            DevLogger.shared.info("[AUDIO DIAG] Node Ptr: \(diagnostics.nodePointer)", context: context)
            DevLogger.shared.info("[AUDIO DIAG] Engine Count: \(allEnginePointers.count)", context: context)
            DevLogger.shared.info("[AUDIO DIAG] All Engine Ptrs: \(Array(allEnginePointers))", context: context)
            #endif
        }
    }
}

