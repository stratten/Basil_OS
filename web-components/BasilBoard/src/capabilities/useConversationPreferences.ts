import { useCallback, useEffect, useRef, useState } from 'react';
import { getConversationWidgetSettings } from '../services/api';

export interface ConversationPreferencesState {
  defaultConversationOnly: boolean;
  refresh: () => void;
}

export function useConversationPreferences(): ConversationPreferencesState {
  const [defaultConversationOnly, setDefaultConversationOnly] = useState(false);
  const mountedRef = useRef(true);

  const refresh = useCallback(() => {
    // Calling inside then() keeps a synchronous throw (including a test mock
    // without this export) on the rejection path instead of breaking render.
    void Promise.resolve()
      .then(() => getConversationWidgetSettings())
      .then((response) => {
        if (!mountedRef.current) return;
        setDefaultConversationOnly(response?.settings?.default_conversation_only === true);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    refresh();
    window.addEventListener('focus', refresh);
    return () => {
      mountedRef.current = false;
      window.removeEventListener('focus', refresh);
    };
  }, [refresh]);

  return { defaultConversationOnly, refresh };
}
