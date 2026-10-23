export interface SwiftMessageHandler {
  // `any` because tests assign `ReturnType<typeof vi.fn>`, which has no call signature and is not assignable to a typed function.
  postMessage: any;
}

declare global {
  interface Window {
    webkit?: {
      messageHandlers: Record<string, SwiftMessageHandler | undefined>;
    };
  }
}

export type MissingHandlerReporter = (message: unknown) => void;

export interface SwiftBridgeOptions {
  onMissing?: MissingHandlerReporter;
}

export interface SwiftBridge<Outgoing> {
  readonly handlerName: string;
  isAvailable: () => boolean;
  post: (message: Outgoing) => boolean;
}

export function hasSwiftHandler(handlerName: string): boolean {
  return Boolean(window.webkit?.messageHandlers?.[handlerName]);
}

export function postToSwiftHandler(handlerName: string, message: unknown, onMissing?: MissingHandlerReporter): boolean {
  const handler = window.webkit?.messageHandlers?.[handlerName];
  if (!handler) {
    onMissing?.(message);
    return false;
  }
  handler.postMessage(message);
  return true;
}

export function missingHandlerLogger(level: 'log' | 'warn' | 'error', text: string): MissingHandlerReporter {
  return (message) => {
    // eslint-disable-next-line no-console
    console[level](text, message);
  };
}

export function createSwiftBridge<Outgoing = unknown>(handlerName: string, options: SwiftBridgeOptions = {}): SwiftBridge<Outgoing> {
  return {
    handlerName,
    isAvailable: () => hasSwiftHandler(handlerName),
    post: (message) => postToSwiftHandler(handlerName, message, options.onMissing),
  };
}
