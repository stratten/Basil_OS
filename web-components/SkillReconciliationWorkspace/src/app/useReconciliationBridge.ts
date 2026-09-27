import { useEffect, useSyncExternalStore } from 'react';
import { registerInitHandler, registerThemeHandler } from '../services/bridge';
import { wsManager } from '../services/websocket';
import { applyHostFonts, applyHostTheme } from './themeBootstrap';
import { store, type StoreState } from './reconciliationStore';

/**
 * Wires the Swift bridge (init/theme), connects the shared /ws bus, hydrates
 * the session, and exposes the store state to React. The workspace session is
 * created by Settings' "Open" action (POST /session) before the window loads,
 * so the webview only needs to hydrate + stream.
 */
export function useReconciliationBridge(): StoreState {
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);

  useEffect(() => {
    let connectedUrl: string | null = null;

    registerThemeHandler((theme, fonts) => {
      applyHostTheme(theme);
      applyHostFonts(fonts);
    });

    registerInitHandler((config) => {
      store.init(config);
      if (config.theme) applyHostTheme(config.theme);
      if (config.fonts) applyHostFonts(config.fonts);

      if (connectedUrl !== config.wsUrl) {
        connectedUrl = config.wsUrl;
        wsManager.connect(config.wsUrl);
      }
      void store.refetchSession();
    });

    const unsubscribeEvents = wsManager.subscribe((event) => store.handleEvent(event));
    const unsubscribeConnect = wsManager.onConnect(() => {
      void store.refetchSession();
    });

    return () => {
      unsubscribeEvents();
      unsubscribeConnect();
      wsManager.disconnect();
    };
  }, []);

  return state;
}
