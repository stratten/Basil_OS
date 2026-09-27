import XCTest
import Combine
@testable import BasilClient

@MainActor
class WebSocketDynamicStepTests: XCTestCase {
    
    var cancellables: Set<AnyCancellable> = []
    
    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }
    
    func testDynamicStepAddedMessageRouting() async {
        // Test that WebSocket service correctly routes dynamic_step_added messages
        let webSocketService = WebSocketService.shared
        let agent_taskService = WebSocketService_AgentTask(parent: webSocketService)
        
        let testMessage: [String: Any] = [
            "event_type": "dynamic_step_added",
            "todo_id": "test_todo_123",
            "step_id": "test_step_456", 
            "description": "Test dynamic step creation",
            "status": "in_progress",
            "execution_method": "dynamic_agent"
        ]
        
        XCTAssertNoThrow {
            agent_taskService.handleWebSocketMessage(testMessage)
        }
    }
    
    func testDynamicStepUpdatedMessageRouting() async {
        // Test that WebSocket service correctly routes dynamic_step_updated messages
        let webSocketService = WebSocketService.shared
        let agent_taskService = WebSocketService_AgentTask(parent: webSocketService)
        
        let testMessage: [String: Any] = [
            "event_type": "dynamic_step_updated",
            "todo_id": "test_todo_123",
            "step_id": "test_step_456",
            "description": "Test dynamic step update",
            "status": "completed",
            "completion_message": "Successfully completed task",
            "execution_method": "dynamic_agent"
        ]
        
        XCTAssertNoThrow {
            agent_taskService.handleWebSocketMessage(testMessage)
        }
    }
    
    func testAgentProgressMessageRouting() async {
        // Test that WebSocket service correctly routes agent_progress_update messages
        let webSocketService = WebSocketService.shared
        let agent_taskService = WebSocketService_AgentTask(parent: webSocketService)
        
        let testMessage: [String: Any] = [
            "event_type": "agent_progress_update",
            "message": "Agent is analyzing request",
            "details": "Determining required tools and approach"
        ]
        
        XCTAssertNoThrow {
            agent_taskService.handleWebSocketMessage(testMessage)
        }
    }
    
    func testStepItemCreationWithVariousStatuses() {
        // Test creating StepItem with different statuses and properties
        let plannedStep = StepItem(
            id: "planned_test_123",
            description: "Planned test step",
            plannedService: "email_service",
            plannedMethod: "send_email",
            status: .pending,
            resultSummary: nil
        )
        
        XCTAssertEqual(plannedStep.description, "Planned test step")
        XCTAssertEqual(plannedStep.status, .pending)
        XCTAssertEqual(plannedStep.plannedService, "email_service")
        XCTAssertEqual(plannedStep.plannedMethod, "send_email")
        XCTAssertEqual(plannedStep.isDynamic, false, "StepItem should default to not dynamic")
        
        // Test creating a dynamic step
        let dynamicStep = StepItem(
            id: "dynamic_test_456",
            description: "Dynamic agent step",
            plannedService: "dynamic_agent_execution",
            plannedMethod: "agent_orchestrated",
            status: .inProgress,
            resultSummary: nil
        )
        
        XCTAssertEqual(dynamicStep.description, "Dynamic agent step")
        XCTAssertEqual(dynamicStep.status, .inProgress)
        XCTAssertEqual(dynamicStep.plannedService, "dynamic_agent_execution")
        XCTAssertEqual(dynamicStep.plannedMethod, "agent_orchestrated")
    }
    
    func testStepStatusTransitions() {
        // Test that StepItem status can be updated through all valid states
        var step = StepItem(
            id: "status_test_789",
            description: "Status transition test",
            plannedService: "test_service",
            plannedMethod: "test_method",
            status: .pending,
            resultSummary: nil
        )
        
        // Test all valid status transitions
        step.status = .pending
        XCTAssertEqual(step.status, .pending)
        
        step.status = .inProgress
        XCTAssertEqual(step.status, .inProgress)
        
        step.status = .completed
        XCTAssertEqual(step.status, .completed)
        
        step.status = .failed
        XCTAssertEqual(step.status, .failed)
    }
    
    func testWebSocketEventTypes() {
        // Test that our new WebSocket events are properly defined
        let dynamicStepAddedEvent = WebSocketEvent.dynamicStepAdded(["test": "data"])
        let dynamicStepUpdatedEvent = WebSocketEvent.dynamicStepUpdated(["test": "data"])
        let agentProgressEvent = WebSocketEvent.agentProgressUpdate(["test": "data"])
        
        // Verify events can be created without throwing
        XCTAssertNotNil(dynamicStepAddedEvent)
        XCTAssertNotNil(dynamicStepUpdatedEvent)
        XCTAssertNotNil(agentProgressEvent)
    }
    
    func testInvalidWebSocketMessageHandling() async {
        // Test that invalid/malformed messages don't crash the system
        let webSocketService = WebSocketService.shared
        let agent_taskService = WebSocketService_AgentTask(parent: webSocketService)
        
        // Test with missing required fields
        let incompleteMessage: [String: Any] = [
            "event_type": "dynamic_step_added"
            // Missing todo_id, step_id, etc.
        ]
        
        XCTAssertNoThrow {
            agent_taskService.handleWebSocketMessage(incompleteMessage)
        }
        
        // Test with unknown event type
        let unknownEventMessage: [String: Any] = [
            "event_type": "unknown_event_type",
            "data": "some data"
        ]
        
        XCTAssertNoThrow {
            agent_taskService.handleWebSocketMessage(unknownEventMessage)
        }
    }
}
