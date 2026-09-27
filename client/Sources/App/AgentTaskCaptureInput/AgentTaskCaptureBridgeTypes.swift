import Foundation
import AppKit

/// Full-snapshot capture state pushed to React on every non-audio-level
/// change. This is a full snapshot, not a partial delta, on purpose.
struct CaptureSnapshot {
    let revision: Int
    let inputModality: String // "voice" | "text"
    let isCapturing: Bool
    let hasCompleted: Bool
    let statusMessage: String
    let wordsDetected: [String]
    let silenceDetectionActive: Bool
    let silenceRemaining: Double
    let useIntelligentCapture: Bool
    let progressPercentage: CGFloat
    let remainingSeconds: Int
    let agentTaskHotkeyDisplay: String?
    let textPrompt: String
    let isSubmittingTextPrompt: Bool
    let selectedModelId: String?
    let referencePaths: [ReferencePathEntry]
    let isDraggingOver: Bool

    /// `path`/`isDirectory` pair mirroring the TypeScript `ReferencePathEntry`.
    struct ReferencePathEntry {
        let path: String
        let isDirectory: Bool

        var jsonObject: [String: Any] {
            ["path": path, "isDirectory": isDirectory]
        }
    }

    /// `[String: Any]` shape matching `CaptureSnapshot` in
    /// `web-components/AgentTaskCaptureInput/src/types.ts`
    /// field-for-field.
    var jsonObject: [String: Any] {
        [
            "revision": revision,
            "inputModality": inputModality,
            "isCapturing": isCapturing,
            "hasCompleted": hasCompleted,
            "statusMessage": statusMessage,
            "wordsDetected": wordsDetected,
            "silenceDetectionActive": silenceDetectionActive,
            "silenceRemaining": silenceRemaining,
            "useIntelligentCapture": useIntelligentCapture,
            "progressPercentage": Double(progressPercentage),
            "remainingSeconds": remainingSeconds,
            "agentTaskHotkeyDisplay": agentTaskHotkeyDisplay ?? NSNull(),
            "textPrompt": textPrompt,
            "isSubmittingTextPrompt": isSubmittingTextPrompt,
            "selectedModelId": selectedModelId ?? NSNull(),
            "referencePaths": referencePaths.map { $0.jsonObject },
            "isDraggingOver": isDraggingOver,
        ]
    }

    /// Builds a snapshot from the current state of the oracle view model plus
    /// the window controller's own `isDraggingOver` flag.
    @MainActor
    static func from(
        viewModel: AgentTaskCaptureViewModel,
        isDraggingOver: Bool,
        revision: Int
    ) -> CaptureSnapshot {
        CaptureSnapshot(
            revision: revision,
            inputModality: viewModel.isTextEntryMode ? "text" : "voice",
            isCapturing: viewModel.isCapturing,
            hasCompleted: viewModel.hasCompleted,
            statusMessage: viewModel.statusMessage,
            wordsDetected: viewModel.wordsDetected,
            silenceDetectionActive: viewModel.silenceDetectionActive,
            silenceRemaining: viewModel.silenceRemaining,
            useIntelligentCapture: viewModel.useIntelligentCapture,
            progressPercentage: viewModel.progressPercentage,
            remainingSeconds: viewModel.remainingSeconds,
            agentTaskHotkeyDisplay: HotkeyService.shared.hotkeyBindings["agentTask"]?.displayString,
            textPrompt: viewModel.textPrompt,
            isSubmittingTextPrompt: viewModel.isSubmittingTextPrompt,
            selectedModelId: viewModel.selectedAgentTaskModelId,
            referencePaths: viewModel.referencePaths.map {
                var isDir: ObjCBool = false
                FileManager.default.fileExists(atPath: $0.path, isDirectory: &isDir)
                return ReferencePathEntry(path: $0.path, isDirectory: isDir.boolValue)
            },
            isDraggingOver: isDraggingOver
        )
    }
}

struct CaptureModelPickerOption: Equatable {
    let id: String
    let displayName: String
    let category: String
}

struct CaptureModelPickerAnchorRect: Equatable {
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat
}

/// JS -> Swift intents. Parsed via `parse(body:)`, mirroring the
/// established manual-dictionary-parsing convention.
enum CaptureInputMessage: Equatable {
    case captureInputReady
    case requestSnapshot
    case requestCaptureResize(width: CGFloat, height: CGFloat)
    case captureHeaderExtent(height: CGFloat)
    case enterVoiceMode
    case enterTextEntryMode
    case updateTextDraft(text: String)
    case submitTextPrompt(text: String, modelId: String?)
    case setSelectedModel(modelId: String?)
    case showNativeModelPicker(models: [CaptureModelPickerOption], selectedModelId: String?, anchorRect: CaptureModelPickerAnchorRect)
    case cancelCapture
    case pickReferenceFiles
    case removeReferencePath(index: Int)
    case openReferencePath(path: String)
    case filesDropped(paths: [String])
    case setDraggingOver(isDraggingOver: Bool)
    case showHistory
    case unknown(rawType: String)

    /// Returns `nil` only when `body` is not a `[String: Any]` or has no
    /// string `type` field. Returns `.unknown(rawType:)` when `type` is
    /// present but unrecognized or missing a required field.
    static func parse(body: Any) -> CaptureInputMessage? {
        guard let dict = body as? [String: Any], let type = dict["type"] as? String else {
            return nil
        }
        switch type {
        case "captureInputReady":
            return .captureInputReady
        case "requestSnapshot":
            return .requestSnapshot
        case "requestCaptureResize":
            guard let width = dict["width"] as? CGFloat, let height = dict["height"] as? CGFloat else {
                return .unknown(rawType: type)
            }
            return .requestCaptureResize(width: width, height: height)
        case "captureHeaderExtent":
            guard let height = dict["height"] as? NSNumber,
                  height.doubleValue.isFinite,
                  height.doubleValue > 0 else {
                return .unknown(rawType: type)
            }
            return .captureHeaderExtent(height: CGFloat(truncating: height))
        case "enterVoiceMode":
            return .enterVoiceMode
        case "enterTextEntryMode":
            return .enterTextEntryMode
        case "updateTextDraft":
            guard let text = dict["text"] as? String else { return .unknown(rawType: type) }
            return .updateTextDraft(text: text)
        case "submitTextPrompt":
            guard let text = dict["text"] as? String else { return .unknown(rawType: type) }
            return .submitTextPrompt(text: text, modelId: dict["modelId"] as? String)
        case "setSelectedModel":
            if dict["modelId"] is NSNull {
                return .setSelectedModel(modelId: nil)
            }
            guard let modelId = dict["modelId"] as? String, !modelId.isEmpty else {
                return .unknown(rawType: type)
            }
            return .setSelectedModel(modelId: modelId)
        case "showNativeModelPicker":
            guard let rawModels = dict["models"] as? [[String: Any]], !rawModels.isEmpty,
                  let rawAnchorRect = dict["anchorRect"] as? [String: Any] else {
                return .unknown(rawType: type)
            }
            let models = rawModels.compactMap { rawModel -> CaptureModelPickerOption? in
                guard let id = rawModel["id"] as? String, !id.isEmpty,
                      let displayName = rawModel["displayName"] as? String, !displayName.isEmpty,
                      let category = rawModel["category"] as? String,
                      ["local", "api", "custom"].contains(category) else {
                    return nil
                }
                return CaptureModelPickerOption(id: id, displayName: displayName, category: category)
            }
            guard models.count == rawModels.count,
                  let x = rawAnchorRect["x"] as? NSNumber,
                  let y = rawAnchorRect["y"] as? NSNumber,
                  let width = rawAnchorRect["width"] as? NSNumber,
                  let height = rawAnchorRect["height"] as? NSNumber else {
                return .unknown(rawType: type)
            }
            let selectedModelId: String?
            if dict["selectedModelId"] is NSNull {
                selectedModelId = nil
            } else if let modelId = dict["selectedModelId"] as? String {
                selectedModelId = modelId
            } else {
                return .unknown(rawType: type)
            }
            return .showNativeModelPicker(
                models: models,
                selectedModelId: selectedModelId,
                anchorRect: CaptureModelPickerAnchorRect(
                    x: CGFloat(truncating: x),
                    y: CGFloat(truncating: y),
                    width: CGFloat(truncating: width),
                    height: CGFloat(truncating: height)
                )
            )
        case "cancelCapture":
            return .cancelCapture
        case "pickReferenceFiles":
            return .pickReferenceFiles
        case "removeReferencePath":
            guard let index = dict["index"] as? Int else { return .unknown(rawType: type) }
            return .removeReferencePath(index: index)
        case "openReferencePath":
            guard let path = dict["path"] as? String else { return .unknown(rawType: type) }
            return .openReferencePath(path: path)
        case "filesDropped":
            guard let paths = dict["paths"] as? [String] else { return .unknown(rawType: type) }
            return .filesDropped(paths: paths)
        case "setDraggingOver":
            guard let isDraggingOver = dict["isDraggingOver"] as? Bool else { return .unknown(rawType: type) }
            return .setDraggingOver(isDraggingOver: isDraggingOver)
        case "showHistory":
            return .showHistory
        default:
            return .unknown(rawType: type)
        }
    }
}
