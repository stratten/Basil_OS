import SwiftUI

@MainActor
struct CapabilityIntroduction_VoiceComparison: View {
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "arrow.left.arrow.right.circle.fill")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text("\(BasilTeamIdentity.assistantSession.displayName) vs \(BasilTeamIdentity.agentTask.displayName)")
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("Two powerful voice features — here's how to choose the right one")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // Side-by-side comparison
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text(BasilTeamIdentity.assistantSession.displayName).font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        comparisonBullet("Quick, single-shot text generation")
                        comparisonBullet("Automatically reads your screen for context")
                        comparisonBullet("Perfect for drafts, replies, and summaries")
                        comparisonBullet("Results paste directly into your active window")
                        comparisonBullet("No selection required — just speak your request")
                    }
                }

                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text(BasilTeamIdentity.agentTask.displayName).font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        comparisonBullet("Multi-step agentic workflows")
                        comparisonBullet("Can perform research and use tools")
                        comparisonBullet("Perfect for complex analysis and planning")
                        comparisonBullet("Results appear in a dedicated panel")
                        comparisonBullet("Can break down big tasks into clear action plans")
                    }
                }

                // When to use each
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Use \(BasilTeamIdentity.assistantSession.displayName) when:").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        whenBullet("You need to draft a quick reply or summary")
                        whenBullet("You want immediate paste to your current app")
                        whenBullet("You're working with visible content on screen")
                        whenBullet("The task is straightforward and content-focused")
                    }
                }

                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Use \(BasilTeamIdentity.agentTask.displayName) when:").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        whenBullet("You need research or information gathering")
                        whenBullet("The task requires multiple steps or tool use")
                        whenBullet("You want to review and edit before using the result")
                        whenBullet("You're doing analysis, planning, or strategy work")
                    }
                }

                // Key differences table
                VStack(alignment: .leading, spacing: 8) {
                    Text("Quick comparison").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    
                    VStack(spacing: 0) {
                        // Table Header
                        HStack(spacing: 0) {
                            Text("")
                                .frame(width: 100, alignment: .leading)
                            
                            Text(BasilTeamIdentity.assistantSession.displayName)
                                .font(AestheticSystem.Typography.bodyMedium)
                                .foregroundColor(AestheticSystem.Colors.primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            
                            Text(BasilTeamIdentity.agentTask.displayName)
                                .font(AestheticSystem.Typography.bodyMedium)
                                .foregroundColor(AestheticSystem.Colors.primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.vertical, 8)
                        .padding(.horizontal, 12)
                        .background(Color(NSColor.controlBackgroundColor).opacity(0.5))
                        
                        Divider()
                        
                        // Table Rows
                        VStack(spacing: 0) {
                            comparisonRow(aspect: "Output", suggestions: "Instant paste", agentTasks: "Panel with options")
                            Divider()
                            comparisonRow(aspect: "Context", suggestions: "Auto screen reading", agentTasks: "Manual if needed")
                            Divider()
                            comparisonRow(aspect: "Complexity", suggestions: "Single-shot", agentTasks: "Multi-step")
                            Divider()
                            comparisonRow(aspect: "Best for", suggestions: "Content creation", agentTasks: "Research & planning")
                        }
                    }
                    .background(Color(NSColor.controlBackgroundColor))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.gray.opacity(0.2), lineWidth: 1)
                    )
                }
            }
            .padding(32)
        }
    }

    // MARK: - Bullets
    @ViewBuilder
    private func comparisonBullet(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text("•")
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
            Text(text)
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
        }
    }
    
    @ViewBuilder
    private func whenBullet(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text("•")
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
            Text(text)
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
        }
    }
    
    @ViewBuilder
    private func comparisonRow(aspect: String, suggestions: String, agentTasks: String) -> some View {
        HStack(spacing: 0) {
            Text(aspect)
                .font(AestheticSystem.Typography.bodyMedium)
                .foregroundColor(.secondary)
                .frame(width: 100, alignment: .leading)
            
            Text(suggestions)
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
            
            Text(agentTasks)
                .font(AestheticSystem.Typography.body)
                .foregroundColor(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 12)
    }
}

struct CapabilityIntroduction_VoiceComparison_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_VoiceComparison()
            .frame(width: 680, height: 520)
    }
}

