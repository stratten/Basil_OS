import Foundation

enum AudioCaptureError: Error {
    case engineNotRunning
    case formatError
    case permissionDenied
    case deviceUnavailable
    case configurationFailed(String)
    case noInputFormat
    case invalidOutputFormat
    case converterCreationFailed
    case systemPermissionRequired
}

