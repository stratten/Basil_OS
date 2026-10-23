import AppKit
import AVFoundation
import Combine
import UniformTypeIdentifiers

@MainActor
final class AudioFileUploadViewModel: ObservableObject {
    @Published var selectedFileURL: URL?
    @Published var fileSize: String?
    @Published var fileDuration: Double?
    @Published var description: String = ""
    @Published var selectedLanguage: String = "auto"
    @Published var isUploading = false
    @Published var uploadStatus = "Preparing upload..."
    @Published var transcriptionResult: String?
    @Published var showError = false
    @Published var errorMessage = ""

    var canUpload: Bool {
        selectedFileURL != nil
    }

    func handleDrop(providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }

        if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { urlData, _ in
                DispatchQueue.main.async {
                    if let urlData = urlData as? Data,
                       let url = NSURL(absoluteURLWithDataRepresentation: urlData, relativeTo: nil) as URL? {
                        let supportedExtensions = ["mp3", "wav", "m4a", "aac", "flac", "ogg"]
                        if supportedExtensions.contains(url.pathExtension.lowercased()) {
                            self.selectedFileURL = url
                            self.loadFileDetails()
                        } else {
                            self.errorMessage = "Please drop a supported audio file format"
                            self.showError = true
                        }
                    }
                }
            }
            return true
        }
        return false
    }

    func loadFileDetails() {
        guard let url = selectedFileURL else { return }

        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            if let size = attributes[.size] as? NSNumber {
                let formatter = ByteCountFormatter()
                formatter.allowedUnits = [.useMB, .useKB]
                formatter.countStyle = .file
                fileSize = formatter.string(fromByteCount: Int64(truncating: size))
            }
        } catch {
            print("Error getting file size: \(error.localizedDescription)")
        }

        loadAudioDuration(from: url)
    }

    private func loadAudioDuration(from url: URL) {
        let asset = AVAsset(url: url)
        let durationTask = Task {
            do {
                let duration = try await asset.load(.duration)
                let seconds = CMTimeGetSeconds(duration)

                await MainActor.run {
                    self.fileDuration = seconds
                }
            } catch {
                print("Error getting duration: \(error.localizedDescription)")
            }
        }

        Task {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if !durationTask.isCancelled {
                durationTask.cancel()
            }
        }
    }

    func uploadFile() async {
        guard let url = selectedFileURL else { return }

        await MainActor.run {
            self.isUploading = true
            self.uploadStatus = "Uploading audio file..."
            self.transcriptionResult = nil
            self.showError = false
            self.errorMessage = ""
        }

        do {
            await MainActor.run {
                self.uploadStatus = "Uploading audio file to server..."
            }

            let responseData = try await APIClient.shared.uploadAudioFile(
                fileURL: url,
                language: selectedLanguage,
                description: description.isEmpty ? nil : description
            )

            await MainActor.run {
                self.uploadStatus = "Processing transcription..."
            }

            if let transcriptionResponse = try? JSONDecoder().decode(TranscriptionResponse.self, from: responseData) {
                await MainActor.run {
                    self.transcriptionResult = transcriptionResponse.text
                    self.isUploading = false
                }
            } else if let responseString = String(data: responseData, encoding: .utf8) {
                await MainActor.run {
                    self.transcriptionResult = responseString
                    self.isUploading = false
                }
            } else {
                throw APIError.decodingFailed(NSError(domain: "AudioFileUpload", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not decode response"]))
            }
        } catch let error as APIError {
            await handleUploadError(error)
        } catch {
            await handleUploadError(error)
        }
    }

    private func handleUploadError(_ error: Error) async {
        let errorDescription: String

        switch error {
        case let apiError as APIError:
            switch apiError {
            case .connectionFailed(let message):
                errorDescription = "Connection failed: \(message)"
            case .invalidResponse:
                errorDescription = "Invalid response from server"
            case .decodingFailed:
                errorDescription = "Could not decode the server response"
            case .backendNotAvailable:
                errorDescription = "The transcription server is currently unavailable"
            case .invalidURL:
                errorDescription = "Invalid URL for audio file"
            case .serverError(let statusCode):
                errorDescription = "Server error (Status \(statusCode))"
            }
        default:
            errorDescription = error.localizedDescription
        }

        await MainActor.run {
            self.isUploading = false
            self.errorMessage = "Failed to upload file: \(errorDescription)"
            self.showError = true
        }
    }
}

struct TranscriptionResponse: Decodable {
    let text: String
    let duration: Double?
    let language: String?

    enum CodingKeys: String, CodingKey {
        case text
        case duration
        case language
    }
}
