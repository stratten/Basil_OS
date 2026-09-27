import SwiftUI
import AppKit
import Foundation

@MainActor
class StartupLoadingWindowController: NSWindowController {
    var viewModel: StartupLoadingViewModel?
    
    init() {
        // Create the window
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 160),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        
        window.title = "Basil"
        window.center()
        window.level = .floating
        window.isReleasedWhenClosed = false
        
        // Create view model
        let viewModel = StartupLoadingViewModel()
        self.viewModel = viewModel
        
        // Create SwiftUI view. The color scheme is derived from the user's
        // configured background (not forced to light), so this window
        // matches the rest of the app's chosen appearance instead of always
        // rendering in light mode.
        let contentView = StartupLoadingView(viewModel: viewModel)
            .preferredColorScheme(AestheticSystem.effectiveColorScheme)
        window.contentView = NSHostingView(rootView: contentView)
        
        super.init(window: window)
        
        // Start monitoring via API
        viewModel.startMonitoring()
        
        // Connect the completion callback
        viewModel.onCompletion { [weak self] in
            self?.hideWindow()
        }
        
        // Show the window immediately
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        
        #if DEBUG
        DevLogger.shared.info("Startup loading window created and displayed", context: "StartupLoadingWindow")
        #endif
    }
    
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }
    
    func hideWindow() {
        window?.orderOut(nil)
        viewModel?.stopMonitoring()
        
        #if DEBUG
        DevLogger.shared.info("Startup loading window hidden", context: "StartupLoadingWindow")
        #endif
    }
}

@MainActor
class StartupLoadingViewModel: ObservableObject {
    @Published var currentMessage = "Starting Basil..."
    @Published var currentSpinner = "⠋"
    
    private var monitoringTimer: Timer?
    private var animationTimer: Timer?
    
    // Braille pattern spinning animation (from original transcription code)
    private let spinnerFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    private var frameIndex = 0
    
    private var onCompletionCallback: (() -> Void)?
    
    init() {
        startSpinnerAnimation()
    }
    
    func startMonitoring() {
        #if DEBUG
        DevLogger.shared.info("🔄 StartupLoadingViewModel: StartMonitoring called (API polling)", context: "StartupLoadingWindow")
        #endif
        
        // Ensure any previous timer is stopped before starting a new one.
        monitoringTimer?.invalidate()

        // Start monitoring the status via API
        monitoringTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.fetchAndUpdateStatus()
            }
        }
        
        // Failsafe: hide the window after 15 seconds regardless (increased slightly)
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            Task { @MainActor in
                if self?.monitoringTimer != nil {
                    #if DEBUG
                    DevLogger.shared.warning("Failsafe: Hiding startup window after 15 seconds", context: "StartupLoadingWindow")
                    #endif
                    self?.onCompletionCallback?()
                }
            }
        }
    }
    
    func stopMonitoring() {
        monitoringTimer?.invalidate()
        animationTimer?.invalidate()
        monitoringTimer = nil
        animationTimer = nil
    }
    
    func onCompletion(_ callback: @escaping () -> Void) {
        onCompletionCallback = callback
    }
    
    private func startSpinnerAnimation() {
        animationTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self else { return }
                self.frameIndex = (self.frameIndex + 1) % self.spinnerFrames.count
                self.currentSpinner = self.spinnerFrames[self.frameIndex]
            }
        }
    }
    
    private func fetchAndUpdateStatus() {
        Task {
            do {
                let statusResponse = try await APIClient.shared.fetchStartupStatus()
                let newMessage = statusResponse.message
                
                if newMessage != currentMessage {
                    currentMessage = newMessage
                    #if DEBUG
                    DevLogger.shared.info("Status updated via API: \\(newMessage)", context: "StartupLoadingWindow")
                    #endif
                }
                
                // Check if we're done
                // Ensure this message exactly matches what dev.sh will send via API on final step
                if newMessage.contains("Launching interface") { 
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        Task { @MainActor in
                            self.onCompletionCallback?()
                        }
                    }
                }
            } catch APIError.backendNotAvailable {
                #if DEBUG
                // This is expected early on, so don't spam logs too much.
                // Log it occasionally or if it persists.
                if Int.random(in: 0..<10) == 0 { // Log 1 in 10 times
                    DevLogger.shared.warning("Backend not available yet while fetching startup status.", context: "StartupLoadingWindow")
                }
                #endif
                // Optionally, set a specific message like "Waiting for backend..."
                // if currentMessage == "Starting Basil..." { // Only if still on initial message
                // currentMessage = "Waiting for backend..."
                // }
            } catch {
                #if DEBUG
                DevLogger.shared.warning("Error fetching startup status: \\(error.localizedDescription)", context: "StartupLoadingWindow")
                #endif
                // Decide if we want to show an error message or just keep polling
            }
        }
    }
}

struct StartupLoadingView: View {
    @ObservedObject var viewModel: StartupLoadingViewModel
    
    var body: some View {
        VStack(spacing: 20) {
            // App title
            Text("Basil")
                .font(AestheticSystem.Typography.title1)
                .foregroundColor(AestheticSystem.Colors.textPrimary)
            
            // Loading message with spinner
            HStack(spacing: 8) {
                Text(viewModel.currentSpinner)
                    .font(.system(.title2, design: .monospaced))
                    .foregroundColor(AestheticSystem.Colors.primary)
                
                Text(viewModel.currentMessage)
                    .font(AestheticSystem.Typography.body)
                    .foregroundColor(AestheticSystem.Colors.textPrimary)
            }
            
            Spacer()
                .frame(height: 10)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(30)
        .background(AestheticSystem.Colors.backgroundPrimary)
    }
} 