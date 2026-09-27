import AppKit

enum ModelsSettingsAlertFactory {
    static func makeDeleteModelConfirmationAlert(modelName: String, modelSize: Int64?) -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Delete \"\(modelName)\"?"
        alert.informativeText = informativeText(modelSize: modelSize)
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Delete")
        alert.addButton(withTitle: "Cancel")
        return alert
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
