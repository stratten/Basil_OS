import Foundation
import AVFoundation
import Combine

@MainActor
class TranscriptionHistoryViewModel: ObservableObject {
    @Published var transcriptions: [TranscriptionRecord] = []
    @Published var isLoading: Bool = false
    @Published var error: String? = nil
    @Published var currentlyPlayingID: String? = nil
    @Published var selectedTimeFrame: TimeFrame = .week
    @Published var searchText: String = ""
    @Published var activeRetranscriptionID: String? = nil
    @Published var retranscriptionProgressMessage: String? = nil
    @Published var retranscriptionProgressFraction: Double? = nil
    @Published private(set) var availableRetranscriptionModels: [TranscriptionModelOption] = []
    @Published private(set) var currentGlobalTranscriptionModelId: String = ""
    
    private var audioPlayer: AVAudioPlayer?
    private var audioPlayerDelegate: AudioPlayerDelegate? // Strong reference to delegate
    private var playbackProgressTask: Task<Void, Never>?

    /// A moment in the audio that is currently playing, for the playback bar in Settings.
    struct PlaybackProgress: Equatable {
        let transcriptionID: String
        let positionSeconds: TimeInterval
        let durationSeconds: TimeInterval
    }

    /// Deliberately a plain closure, not `@Published`: the Settings bridge debounces `objectWillChange` into a full snapshot, so a 4 Hz position tick published there would starve the debounce and resend every record.
    var onPlaybackProgress: ((PlaybackProgress) -> Void)?

    private static let playbackProgressInterval: Duration = .milliseconds(250)
    private let api = APIClient.shared
    private var searchTask: Task<Void, Never>? = nil
    private var cancellables = Set<AnyCancellable>()
    
    init() {
        setupWebSocketProgressSubscription()
        Task {
            await loadRetranscriptionModels()
        }
    }
    
    enum TimeFrame: String, CaseIterable, Identifiable {
        case day = "24 Hours"
        case week = "7 Days"
        case month = "30 Days"
        case all = "All Time"
        
        var id: String { self.rawValue }
        
        var days: Int? {
            switch self {
            case .day: return 1
            case .week: return 7
            case .month: return 30
            case .all: return nil
            }
        }
    }
    
    func loadTranscriptions(days: Int? = nil, limit: Int = 50) async {
        isLoading = true
        error = nil
        
        do {
            let response: TranscriptionHistoryResponse
            
            if searchText.isEmpty {
                // No search - use list endpoint
                response = try await api.listTranscriptions(days: days, limit: limit)
            } else {
                // Search with query
                response = try await api.searchTranscriptions(
                    query: searchText,
                    days: days,
                    limit: limit
                )
            }
            
            if response.success {
                self.transcriptions = response.transcriptions
            } else if let errorMsg = response.error {
                self.error = errorMsg
            } else {
                self.error = "Unknown error occurred"
            }
        } catch {
            self.error = searchText.isEmpty ? "Failed to load transcriptions: \(error.localizedDescription)" : "Search failed: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    func performSearch() {
        // Debounce search
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            if !Task.isCancelled {
                await loadTranscriptions(days: selectedTimeFrame.days)
            }
        }
    }
    
    @discardableResult
    func playAudio(for transcription: TranscriptionRecord) async -> Bool {
        // Stop any currently playing audio
        stopAudio()
        error = nil
        
        do {
            // Set the currently playing ID
            currentlyPlayingID = transcription.id
            
            // Get the audio file from the server
            let endpoint = "/transcription/audio/\(transcription.id)"
            let audioData = try await api.get(endpoint)
            
            // Create and play the audio player
            audioPlayer = try AVAudioPlayer(data: audioData)
            
            // Create delegate and keep a strong reference to it
            audioPlayerDelegate = AudioPlayerDelegate { [weak self] in
                Task { @MainActor [weak self] in
                    self?.stopPlaybackProgressUpdates()
                    self?.currentlyPlayingID = nil
                }
            }
            
            // Set the delegate
            audioPlayer?.delegate = audioPlayerDelegate
            
            audioPlayer?.prepareToPlay()
            guard audioPlayer?.play() == true else {
                stopAudio()
                self.error = "Failed to play audio."
                return false
            }
            startPlaybackProgressUpdates()
            return true
        } catch {
            currentlyPlayingID = nil
            self.error = "Failed to play audio: \(error.localizedDescription)"
            return false
        }
    }
    
    /// Keeps a seek target inside the audio: NaN, infinity, and negatives become the start, and anything past the end becomes the end. A zero or unknown duration always yields the start.
    nonisolated static func clampedSeekTarget(_ seconds: TimeInterval, duration: TimeInterval) -> TimeInterval {
        guard seconds.isFinite, duration.isFinite, duration > 0 else { return 0 }
        return min(max(seconds, 0), duration)
    }

    /// Moves the playhead of the audio that is playing and reports the new position straight away; ignored when nothing is playing.
    func seekAudio(toSeconds seconds: TimeInterval) {
        guard let player = audioPlayer, currentlyPlayingID != nil else { return }
        player.currentTime = Self.clampedSeekTarget(seconds, duration: player.duration)
        publishPlaybackProgress()
    }

    private func publishPlaybackProgress() {
        guard let player = audioPlayer, let transcriptionID = currentlyPlayingID,
              player.duration.isFinite, player.duration > 0 else { return }
        let position = Self.clampedSeekTarget(player.currentTime, duration: player.duration)
        onPlaybackProgress?(PlaybackProgress(
            transcriptionID: transcriptionID,
            positionSeconds: position,
            durationSeconds: player.duration
        ))
    }

    private func startPlaybackProgressUpdates() {
        stopPlaybackProgressUpdates()
        publishPlaybackProgress()
        playbackProgressTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: Self.playbackProgressInterval)
                guard !Task.isCancelled, let self else { return }
                self.publishPlaybackProgress()
            }
        }
    }

    private func stopPlaybackProgressUpdates() {
        playbackProgressTask?.cancel()
        playbackProgressTask = nil
    }

    func stopAudio() {
        stopPlaybackProgressUpdates()
        audioPlayer?.stop()
        audioPlayer = nil
        audioPlayerDelegate = nil
        currentlyPlayingID = nil
    }
    
    @discardableResult
    func deleteTranscription(_ transcription: TranscriptionRecord) async -> Bool {
        error = nil
        do {
            let endpoint = "/transcription/\(transcription.id)"
            let response = try await api.delete(endpoint)
            
            // OperationResponse uses status field
            if response.status == "success" {
                // Remove from local array
                self.transcriptions.removeAll { $0.id == transcription.id }
                return true
            } else if let details = response.details {
                self.error = details
            }
            return false
        } catch {
            self.error = "Failed to delete transcription: \(error.localizedDescription)"
            return false
        }
    }
    
    func loadRetranscriptionModels() async {
        let result = await TranscriptionModelOption.loadAll()
        availableRetranscriptionModels = result.allOptions
        currentGlobalTranscriptionModelId = result.currentModelId
    }
    
    func retranscribe(_ transcription: TranscriptionRecord, modelId: String? = nil) async -> Bool {
        error = nil
        activeRetranscriptionID = transcription.id
        retranscriptionProgressMessage = "Preparing retranscription..."
        retranscriptionProgressFraction = nil
        
        do {
            let endpoint = "/transcription/\(transcription.id)/retranscribe"
            let data = try await api.postForData(
                endpoint,
                RetranscribeRequestBody(modelId: modelId)
            )

            let decoder = JSONDecoder()
            let response = try decoder.decode(RetranscribeResponse.self, from: data)

            // Reload the list whether the API call succeeded or failed.
            // On success the backend has updated text, model_name, and
            // timestamp on the row; on failure the lifecycle helper has
            // flipped the row to status=failed with error_message. Either
            // way the local copy in self.transcriptions is now stale and
            // needs to come from the server to show the correct state.
            await loadTranscriptions(days: selectedTimeFrame.days)
            clearRetranscriptionProgress()

            if response.success {
                return true
            }
            if let errorMsg = response.error {
                self.error = errorMsg
            }
            return false
        } catch {
            self.error = "Failed to retranscribe: \(error.localizedDescription)"
            // Even on a transport error, the backend may have already
            // marked the row failed -- refresh so the UI reflects that.
            await loadTranscriptions(days: selectedTimeFrame.days)
            clearRetranscriptionProgress()
            return false
        }
    }
    
    private func setupWebSocketProgressSubscription() {
        WebSocketService.shared.eventSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                guard let self else { return }
                guard self.activeRetranscriptionID != nil else { return }
                
                if case .transcriptionProgress(let payload) = event {
                    if let message = payload["message"] as? String, !message.isEmpty {
                        self.retranscriptionProgressMessage = message
                    }
                    
                    if let progress = payload["stage_progress"] as? Double {
                        self.retranscriptionProgressFraction = min(max(progress, 0.0), 1.0)
                    } else if let current = payload["current_time_seconds"] as? Double,
                              let duration = payload["audio_duration_seconds"] as? Double,
                              duration > 0 {
                        self.retranscriptionProgressFraction = min(max(current / duration, 0.0), 1.0)
                    }
                }
            }
            .store(in: &cancellables)
    }
    
    private func clearRetranscriptionProgress() {
        activeRetranscriptionID = nil
        retranscriptionProgressMessage = nil
        retranscriptionProgressFraction = nil
    }
}

// Response models for delete and retranscribe
struct TranscriptionDeleteResponse: Codable {
    let success: Bool
    let message: String?
    let error: String?
}

struct RetranscribeResponse: Codable {
    let success: Bool
    let text: String?
    let message: String?
    let error: String?
}

struct RetranscribeRequestBody: Codable {
    let modelId: String?
}

// Helper class to handle audio player delegate callbacks
class AudioPlayerDelegate: NSObject, AVAudioPlayerDelegate {
    private let completion: () -> Void
    
    init(completion: @escaping () -> Void) {
        self.completion = completion
        super.init()
    }
    
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        completion()
    }
} 