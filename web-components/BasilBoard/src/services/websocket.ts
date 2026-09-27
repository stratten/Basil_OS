import type {
  ConversationConnectionState,
  ConversationSubmission,
  TodoWorkspaceMessage,
  WSEvent,
} from '../contracts';

type EventHandler = (event: WSEvent) => void;
type ConnectHandler = () => void;
type ConnectionStateHandler = (state: ConversationConnectionState) => void;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private url = '';
  private handlers: EventHandler[] = [];
  private connectHandlers: ConnectHandler[] = [];
  private connectionStateHandlers: ConnectionStateHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private readonly maxReconnectDelay = 30000;
  private shouldReconnect = false;
  private connectionState: ConversationConnectionState = 'closed';

  connect(url: string): void {
    this.url = url;
    this.shouldReconnect = true;
    this.doConnect();
  }

  private setConnectionState(state: ConversationConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    for (const handler of this.connectionStateHandlers) handler(state);
  }

  private doConnect(): void {
    if (!this.shouldReconnect || !this.url) return;
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    this.setConnectionState('connecting');
    try {
      const socket = new WebSocket(this.url);
      this.ws = socket;
      socket.onopen = () => {
        if (this.ws !== socket) return;
        this.reconnectDelay = 1000;
        this.setConnectionState('open');
        for (const handler of this.connectHandlers) handler();
      };
      socket.onmessage = (event) => {
        if (this.ws !== socket) return;
        try {
          const data = JSON.parse(event.data) as WSEvent;
          if (data.event_type) {
            for (const handler of this.handlers) handler(data);
          }
        } catch {
          // Ignore malformed and non-JSON frames without disrupting later events.
        }
      };
      socket.onclose = () => {
        if (this.ws !== socket) return;
        this.ws = null;
        this.setConnectionState('closed');
        this.scheduleReconnect();
      };
      socket.onerror = () => socket.close();
    } catch (error) {
      console.error('[BasilBoard WS] Connection failed:', error);
      this.ws = null;
      this.setConnectionState('closed');
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.doConnect();
    }, this.reconnectDelay);
  }

  sendConversationMessage(submission: ConversationSubmission): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify({
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
      }));
      return true;
    } catch {
      return false;
    }
  }

  sendTodoWorkspaceMessage(message: TodoWorkspaceMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify({
        type: 'todo_workspace_message',
        workspace_id: message.workspaceId,
        request_id: message.requestId,
        message: message.message,
        selected_todo_ids: message.selectedTodoIds,
        reference_paths: message.referencePaths,
        transcript: message.transcript,
        model_id: message.modelId ?? null,
      }));
      return true;
    } catch {
      return false;
    }
  }

  cancelConversationResponse(requestId: string, conversationId?: string): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify({
        type: 'conversation_cancel',
        request_id: requestId,
        conversation_id: conversationId ?? null,
      }));
      return true;
    } catch {
      return false;
    }
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((item) => item !== handler);
    };
  }

  onConnect(handler: ConnectHandler): () => void {
    this.connectHandlers.push(handler);
    return () => {
      this.connectHandlers = this.connectHandlers.filter((item) => item !== handler);
    };
  }

  subscribeConnectionState(handler: ConnectionStateHandler): () => void {
    this.connectionStateHandlers.push(handler);
    handler(this.connectionState);
    return () => {
      this.connectionStateHandlers = this.connectionStateHandlers.filter((item) => item !== handler);
    };
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.ws;
    this.ws = null;
    socket?.close();
    this.setConnectionState('closed');
  }
}

export const basilBoardWebSocket = new WebSocketManager();
