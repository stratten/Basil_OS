import AppKit

enum ModelsSettingsAlertFactory {
    static func makeDeleteModelConfirmationAlert(modelName: String, modelSize: Int64?) -> NSAlert {
        NSAlert(
            title: "Delete \"\(modelName)\"?",
            message: informativeText(modelSize: modelSize),
            style: .warning,
            buttons: ["Delete", "Cancel"]
        )
    }

    static func informativeText(modelSize: Int64?) -> String {
        var sentences = ["Model files will be removed from disk."]
        if let modelSize {
            let formatter = ByteCountFormatter()
            formatter.countStyle = .file
            sentences.append("This will free up approximately \(formatter.string(fromByteCount: modelSize)).")
        }
        sentences.append("The HuggingFace cache at ~/.cache/huggingface/ will also be cleared, which frees additional disk space but means re-downloading if you add this model again later.")
        return sentences.joined(separator: " ")
    }
}
