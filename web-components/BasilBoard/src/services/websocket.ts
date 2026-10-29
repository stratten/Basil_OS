import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import type {
  ConversationSubmission,
  TodoWorkspaceMessage,
  WSEvent,
} from '../contracts';

export class WebSocketManager extends ReconnectingWebSocket<WSEvent> {
  constructor() {
    super({ logLabel: '[BasilBoard WS]' });
  }

  sendConversationMessage(submission: ConversationSubmission): boolean {
    return this.sendJson({
      type: 'conversation_message',
      message: submission.content,
      display_markdown: submission.displayMarkdown,
      message_id: submission.messageId,
      request_id: submission.requestId,
      conversation_id: submission.conversationId ?? null,
      model_id: submission.modelId ?? null,
      file_paths: submission.filePaths,
      delegation_opt_out: submission.delegationOptOut,
      use_streaming: true,
    });
  }

  sendTodoWorkspaceMessage(message: TodoWorkspaceMessage): boolean {
    return this.sendJson({
      type: 'todo_workspace_message',
      workspace_id: message.workspaceId,
      request_id: message.requestId,
      message: message.message,
      selected_todo_ids: message.selectedTodoIds,
      reference_paths: message.referencePaths,
      transcript: message.transcript,
      model_id: message.modelId ?? null,
    });
  }

  cancelConversationResponse(requestId: string, conversationId?: string): boolean {
    return this.sendJson({
      type: 'conversation_cancel',
      request_id: requestId,
      conversation_id: conversationId ?? null,
    });
  }
}

export const basilBoardWebSocket = new WebSocketManager();
