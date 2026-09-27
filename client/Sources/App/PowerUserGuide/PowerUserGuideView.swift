import SwiftUI

/// Container view for the Power User Guide - accessible from Settings
/// Contains all the detailed capability introduction screens for users who want to learn more
struct PowerUserGuideView: View {
    @Binding var isPresented: Bool
    
    enum GuideSection: String, CaseIterable, Identifiable {
        case transcription = "Transcription"
        case assistantSession = "assistant_session"
        case agentTasks = "agent_task"
        case voiceComparison = "Voice Comparison"
        case conversation = "Conversation"
        case activityCapture = "Activity Capture"
        case models = "Models"
        
        var id: String { rawValue }
        
        var label: String {
            switch self {
            case .transcription: return "Transcription"
            case .assistantSession: return BasilTeamIdentity.assistantSession.displayName
            case .agentTasks: return BasilTeamIdentity.agentTask.displayName
            case .voiceComparison: return "Voice Comparison"
            case .conversation: return "Conversation"
            case .activityCapture: return "Activity Capture"
            case .models: return "Models"
            }
        }
        
        var icon: String {
            switch self {
            case .transcription: return "waveform"
            case .assistantSession: return "wand.and.stars"
            case .agentTasks: return "mic.fill"
            case .voiceComparison: return "arrow.left.arrow.right"
            case .conversation: return "bubble.left.and.bubble.right"
            case .activityCapture: return "clock.arrow.circlepath"
            case .models: return "cpu.fill"
            }
        }
    }
    
    @State private var selectedSection: GuideSection = .transcription
    
    var body: some View {
        VStack(spacing: 0) {
            NavigationView {
                // Sidebar - using plain style to avoid native sidebar selection behavior
                List(GuideSection.allCases, id: \.self) { section in
                    Button(action: {
                        selectedSection = section
                    }) {
                        HStack(spacing: 8) {
                            sectionIcon(section)
                            Text(section.label)
                        }
                            .font(AestheticSystem.Typography.body)
                            .foregroundColor(selectedSection == section ? .white : AestheticSystem.Colors.textPrimary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                    .padding(.vertical, 6)
                    .padding(.horizontal, 6)
                    .frame(width: 158)
                    .background(
                        selectedSection == section ?
                        AestheticSystem.Colors.primary.opacity(0.85) : Color.clear
                    )
                    .cornerRadius(6)
                    .listRowInsets(EdgeInsets(top: 2, leading: 4, bottom: 2, trailing: 4))
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                }
                .listStyle(.plain)
                .padding(.top, 12)
                .frame(minWidth: 180, idealWidth: 200, maxWidth: 220)
                .background(AestheticSystem.Colors.backgroundSecondary)
                
                // Content area
                VStack(alignment: .leading, spacing: 0) {
                    contentForSection(selectedSection)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .navigationViewStyle(.automatic)
            
            // Custom compact footer
            HStack {
                Spacer()
                Button(action: { isPresented = false }) {
                    Text("Done")
                        .font(AestheticSystem.Typography.body)
                        .foregroundColor(.white)
                        .padding(.horizontal, 20)
                        .padding(.vertical, 10)
                        .background(AestheticSystem.Colors.primary.opacity(0.85))
                        .cornerRadius(8)
                }
                .buttonStyle(.plain)
                .padding(.trailing, 16)
            }
            .padding(.vertical, 10)
            .background(AestheticSystem.Colors.backgroundSecondary)
            .overlay(
                Divider(),
                alignment: .top
            )
        }
        .frame(minWidth: 900, minHeight: 700)
    }

    @ViewBuilder
    private func sectionIcon(_ section: GuideSection) -> some View {
        if section == .agentTasks {
            Image("PaprikaIcon")
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 16, height: 16)
        } else {
            Image(systemName: section.icon)
                .frame(width: 16, height: 16)
        }
    }
    
    @ViewBuilder
    private func contentForSection(_ section: GuideSection) -> some View {
        switch section {
        case .transcription:
            CapabilityIntroduction_Transcription(onContinue: {})
        case .assistantSession:
            CapabilityIntroduction_AssistantSession()
        case .agentTasks:
            CapabilityIntroduction_AgentTasks()
        case .voiceComparison:
            CapabilityIntroduction_VoiceComparison()
        case .conversation:
            CapabilityIntroduction_Conversation()
        case .activityCapture:
            CapabilityIntroduction_ActivityCapture()
        case .models:
            CapabilityIntroduction_Models()
        }
    }
}

struct PowerUserGuideView_Previews: PreviewProvider {
    static var previews: some View {
        PowerUserGuideView(isPresented: .constant(true))
    }
}

