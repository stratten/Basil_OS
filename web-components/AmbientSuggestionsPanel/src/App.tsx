import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type {
  AmbientRuntimeStatus,
  AmbientSuggestion,
  AmbientSuggestionSettings,
  EvaluationModel,
  FontConfig,
  InitMessage,
  ThemeConfig,
} from './types';
import {
  acceptSuggestion,
  dismissPanel,
  logAmbientPanel,
  minimizePanel,
  notifyAmbientPanelReady,
  notifyAmbientRuntimeChanged,
  registerInitHandler,
  registerModelSelectionHandler,
  registerStatusHandler,
  registerSuggestionHandlers,
  registerThemeHandler,
  requestModelPicker,
  rejectSuggestion,
  requestResize,
  toggleCollapsePanel,
} from './services/bridge';
import { measureCollapsedPanelSize } from './collapsedPanelSizing';
import { applyHostTheme } from './app/themeBootstrap';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';

const PANEL_WIDTH = 360;
const HEADER_HEIGHT = 116;
const EMPTY_HEIGHT = 56;
const CARD_ESTIMATED_HEIGHT = 112;
const MAX_VISIBLE_CARDS = 3;
const SYSTEM_FONT_FALLBACK = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';

function toCssFontFamily(rawName: string | null | undefined): string {
  const trimmed = (rawName ?? '').trim();
  if (!trimmed) {
    return SYSTEM_FONT_FALLBACK;
  }
  const base = trimmed
    .replace(
      /-(?:UltraLight|Thin|ExtraLight|Light|Regular|Book|Medium|Semibold|SemiBold|DemiBold|Bold|ExtraBold|Heavy|Black|Italic|Oblique|Condensed|Compressed|Expanded|Extended|Display|Text|MT)$/i,
      ''
    )
    .trim();
  const needsQuotes = /[\s'"]/.test(base);
  const formatted = needsQuotes ? `"${base.replace(/"/g, '\\"')}"` : base;
  return `${formatted}, ${SYSTEM_FONT_FALLBACK}`;
}

function secondsUntil(timestamp: string | null | undefined, now = Date.now()): number | null {
  if (!timestamp) return null;
  const parsed = new Date(timestamp).getTime();
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.ceil((parsed - now) / 1000));
}

function formatLastEvaluation(timestamp: string | null | undefined): string {
  if (!timestamp) return 'Not evaluated yet';
  const parsed = new Date(timestamp).getTime();
  if (!Number.isFinite(parsed)) return 'Evaluation time unavailable';
  const elapsed = Math.max(0, Math.floor((Date.now() - parsed) / 1000));
  if (elapsed < 5) return 'Evaluated just now';
  if (elapsed < 60) return `Evaluated ${elapsed}s ago`;
  return `Evaluated ${Math.floor(elapsed / 60)}m ago`;
}

function compactProvenance(appName: string | null | undefined, windowTitle: string | null | undefined): string {
  const app = (appName ?? '').trim() || 'Unknown app';
  const window = (windowTitle ?? '').trim();
  return window ? `${app} - ${window}` : app;
}

function shortModelLabel(rawName: string): string {
  const trimmed = rawName.trim();
  if (!trimmed.endsWith(')')) return trimmed;
  const openParen = trimmed.lastIndexOf('(');
  if (openParen < 0) return trimmed;
  const stripped = trimmed.slice(0, openParen).trim();
  return stripped || trimmed;
}

export default function App() {
  const [suggestions, setSuggestions] = useState<AmbientSuggestion[]>([]);
  const [apiBase, setApiBase] = useState<string | null>(null);
  const [status, setStatus] = useState<AmbientRuntimeStatus | null>(null);
  const [models, setModels] = useState<EvaluationModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [frequencySeconds, setFrequencySeconds] = useState(120);
  const [draftFrequencySeconds, setDraftFrequencySeconds] = useState('120');
  const [isBusy, setIsBusy] = useState(false);
  const [isEditingFrequency, setIsEditingFrequency] = useState(false);
  const [isHydrating, setIsHydrating] = useState(false);
  const [modelLoadError, setModelLoadError] = useState<string | null>(null);
  const [panelMessage, setPanelMessage] = useState<string | null>(null);
  const [countdownNow, setCountdownNow] = useState(Date.now());
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);
  const modelPickerButtonRef = useRef<HTMLButtonElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const isEmpty = suggestions.length === 0;
  const nextEvaluationSeconds = secondsUntil(status?.next_evaluation_time, countdownNow);
  const selectedModelEntry = models.find((model) => model.id === selectedModel);
  const selectedModelLabel = selectedModelEntry
    ? shortModelLabel(selectedModelEntry.displayName)
    : selectedModel || (modelLoadError ? 'No models loaded' : 'Select model');
  const hasValidSelectedModel = Boolean(selectedModelEntry);
  const canToggleRuntime = Boolean(apiBase && status?.enabled && hasValidSelectedModel && !isBusy);

  const applyTheme = useCallback((theme: ThemeConfig, fonts?: FontConfig) => {
    applyHostTheme(theme);
    const root = document.documentElement;
    if (theme.processingRgb) root.style.setProperty('--processing-rgb', theme.processingRgb);
    if (fonts) {
      root.style.setProperty('--font-family-light', toCssFontFamily(fonts.fontFamily));
      root.style.setProperty('--font-family-medium', toCssFontFamily(fonts.fontFamilyMedium));
      root.style.setProperty('--font-family-bold', toCssFontFamily(fonts.fontFamilyBold));
    }
  }, []);

  const handleInit = useCallback((config: InitMessage) => {
    applyTheme(config.theme, config.fonts);
    setApiBase(`http://127.0.0.1:${config.port}`);
    logAmbientPanel('log', `Ambient panel initialized with API port ${config.port}`);
  }, [applyTheme]);

  const loadModels = useCallback(async (base: string) => {
    const collected: EvaluationModel[] = [];
    setModelLoadError(null);
    try {
      const installedResponse = await fetch(`${base}/models/installed`);
      if (installedResponse.ok) {
        const installed = await installedResponse.json();
        for (const [modelTypeName, modelType] of Object.entries<any>(installed)) {
          for (const [variantId, variant] of Object.entries<any>(modelType.variants ?? {})) {
            if (variant.valid === true && Array.isArray(variant.capabilities) && variant.capabilities.includes('reasoning')) {
              const displayName = variant.name ?? variant.display_name ?? variant.model_id;
              const modelId = variant.model_id ?? `${modelTypeName}-${variantId}`;
              if (displayName && modelId) {
                collected.push({
                  id: modelId,
                  displayName,
                  isLocal: true,
                });
              }
            }
          }
        }
      } else {
        logAmbientPanel('warn', `Ambient model load failed for /models/installed: ${installedResponse.status}`);
      }

      const apiModelsResponse = await fetch(`${base}/settings/api_models/reasoning`);
      if (apiModelsResponse.ok) {
        const payload = await apiModelsResponse.json();
        if (payload.api_models_enabled || payload.apiModelsEnabled) {
          for (const model of payload.models ?? []) {
            collected.push({
              id: model.id,
              displayName: model.display_name ?? model.displayName ?? model.name ?? model.id,
              isLocal: false,
            });
          }
        }
      } else {
        logAmbientPanel('warn', `Ambient model load failed for API models: ${apiModelsResponse.status}`);
      }

      const sortedModels = collected.sort((left, right) => (
        left.isLocal !== right.isLocal
          ? (left.isLocal ? -1 : 1)
          : left.displayName.localeCompare(right.displayName)
      ));
      setModels(sortedModels);
      if (sortedModels.length === 0) {
        setModelLoadError('No evaluator models loaded');
        logAmbientPanel('warn', 'Ambient panel loaded zero evaluator models');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setModelLoadError('No evaluator models loaded');
      logAmbientPanel('error', `Ambient model load failed: ${message}`);
    }
  }, []);

  const applyRuntimeStatus = useCallback((nextStatus: AmbientRuntimeStatus) => {
    setStatus((current) => (
      JSON.stringify(current) === JSON.stringify(nextStatus) ? current : nextStatus
    ));
    if (nextStatus.evaluation_model) {
      setSelectedModel(nextStatus.evaluation_model);
    }
    if (typeof nextStatus.frequency_seconds === 'number') {
      setFrequencySeconds(nextStatus.frequency_seconds);
      if (!isEditingFrequency) {
        setDraftFrequencySeconds(String(Math.round(nextStatus.frequency_seconds)));
      }
    }
  }, [isEditingFrequency]);

  const applySettings = useCallback((settings: AmbientSuggestionSettings) => {
    if (settings.evaluation_model) {
      setSelectedModel(settings.evaluation_model);
    }
    if (typeof settings.frequency_seconds === 'number') {
      setFrequencySeconds(settings.frequency_seconds);
      if (!isEditingFrequency) {
        setDraftFrequencySeconds(String(Math.round(settings.frequency_seconds)));
      }
    }
  }, [isEditingFrequency]);

  const refreshStatusBaseline = useCallback(async (base = apiBase) => {
    if (!base) return;
    try {
      const response = await fetch(`${base}/ambient-suggestions/status`);
      if (response.ok) {
        applyRuntimeStatus(await response.json());
      } else {
        logAmbientPanel('warn', `Ambient status baseline failed: HTTP ${response.status}`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logAmbientPanel('error', `Ambient status baseline failed: ${message}`);
    }
  }, [apiBase, applyRuntimeStatus]);

  const hydratePanel = useCallback(async (base = apiBase) => {
    if (!base) return;
    setIsHydrating(true);
    try {
      const [statusResult, settingsResult, suggestionsResult] = await Promise.allSettled([
        fetch(`${base}/ambient-suggestions/status`),
        fetch(`${base}/settings/ambient-suggestions`),
        fetch(`${base}/ambient-suggestions/suggestions`),
      ]);

      let nextStatus: AmbientRuntimeStatus | null = null;
      let settings: AmbientSuggestionSettings | null = null;

      if (statusResult.status === 'fulfilled' && statusResult.value.ok) {
        nextStatus = await statusResult.value.json() as AmbientRuntimeStatus;
        applyRuntimeStatus(nextStatus);
      } else {
        const reason = statusResult.status === 'fulfilled' ? `HTTP ${statusResult.value.status}` : statusResult.reason;
        logAmbientPanel('warn', `Ambient status hydration failed: ${reason}`);
      }

      if (settingsResult.status === 'fulfilled' && settingsResult.value.ok) {
        const payload = await settingsResult.value.json();
        settings = payload.settings ?? null;
      } else {
        const reason = settingsResult.status === 'fulfilled' ? `HTTP ${settingsResult.value.status}` : settingsResult.reason;
        logAmbientPanel('warn', `Ambient settings hydration failed: ${reason}`);
      }

      if (suggestionsResult.status === 'fulfilled' && suggestionsResult.value.ok) {
        const openSuggestions = await suggestionsResult.value.json();
        if (Array.isArray(openSuggestions)) {
          setSuggestions(openSuggestions);
        }
      } else {
        const reason = suggestionsResult.status === 'fulfilled' ? `HTTP ${suggestionsResult.value.status}` : suggestionsResult.reason;
        logAmbientPanel('warn', `Ambient suggestions hydration failed: ${reason}`);
      }

      if (settings) {
        applySettings(settings);
      }
      if (!settings && !nextStatus) {
        setPanelMessage('Unable to load Ambient settings.');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPanelMessage('Unable to load Ambient settings.');
      logAmbientPanel('error', `Ambient runtime refresh failed: ${message}`);
    } finally {
      setIsHydrating(false);
    }
  }, [apiBase, applyRuntimeStatus, applySettings]);

  const updateOperationalSettings = useCallback(async (patch: Record<string, string | number>) => {
    if (!apiBase) return;
    setIsBusy(true);
    try {
      const response = await fetch(`${apiBase}/settings/ambient-suggestions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (response.ok) {
        const payload = await response.json().catch(() => null);
        if (payload?.updated_settings) {
          applySettings(payload.updated_settings);
        }
        await refreshStatusBaseline(apiBase);
        notifyAmbientRuntimeChanged();
      }
    } finally {
      setIsBusy(false);
    }
  }, [apiBase, applySettings, refreshStatusBaseline]);

  const selectModel = useCallback((modelId: string) => {
    if (!models.some((model) => model.id === modelId)) {
      setPanelMessage('Choose an evaluator model from the list before starting.');
      return;
    }
    setSelectedModel(modelId);
    void updateOperationalSettings({ evaluation_model: modelId });
  }, [models, updateOperationalSettings]);

  const showNativeModelPicker = useCallback(() => {
    const button = modelPickerButtonRef.current;
    if (!button || models.length === 0 || isBusy) return;
    const rect = button.getBoundingClientRect();
    requestModelPicker(models, selectedModel, {
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height,
    });
  }, [isBusy, models, selectedModel]);

  const toggleRuntime = useCallback(async () => {
    if (!apiBase) return;
    if (!selectedModel) {
      setPanelMessage('Choose an evaluator model before starting.');
      return;
    }
    if (!hasValidSelectedModel) {
      setPanelMessage('Choose an evaluator model from the list before starting.');
      return;
    }
    setIsBusy(true);
    try {
      const endpoint = status?.is_running ? 'stop' : 'start';
      const response = await fetch(`${apiBase}/ambient-suggestions/${endpoint}`, { method: 'POST' });
      if (response.ok) {
        const payload = await response.json();
        setPanelMessage(payload.message ?? null);
        await refreshStatusBaseline(apiBase);
        notifyAmbientRuntimeChanged();
      } else {
        const payload = await response.json().catch(() => null);
        const detail = payload?.detail ?? `HTTP ${response.status}`;
        setPanelMessage(`Proactive Suggestions ${endpoint} failed: ${detail}`);
        logAmbientPanel('warn', `Proactive Suggestions ${endpoint} failed: ${detail}`);
      }
    } finally {
      setIsBusy(false);
    }
  }, [apiBase, hasValidSelectedModel, refreshStatusBaseline, selectedModel, status?.is_running]);

  const commitFrequencySeconds = useCallback((rawValue: string) => {
    const parsed = Number(rawValue);
    const clamped = Number.isFinite(parsed)
      ? Math.min(Math.max(Math.round(parsed), 1), 3600)
      : Math.round(frequencySeconds);
    setFrequencySeconds(clamped);
    setDraftFrequencySeconds(String(clamped));
    setIsEditingFrequency(false);
    void updateOperationalSettings({ frequency_seconds: clamped });
  }, [frequencySeconds, updateOperationalSettings]);

  const stepFrequencySeconds = useCallback((delta: number) => {
    const nextValue = Math.min(Math.max(Math.round(frequencySeconds + delta), 1), 3600);
    setFrequencySeconds(nextValue);
    setDraftFrequencySeconds(String(nextValue));
    void updateOperationalSettings({ frequency_seconds: nextValue });
  }, [frequencySeconds, updateOperationalSettings]);

  useEffect(() => {
    if (!apiBase) return;
    void hydratePanel(apiBase);
    void loadModels(apiBase);
  }, [apiBase, hydratePanel, loadModels]);

  useEffect(() => {
    if (!status?.is_running || !status.next_evaluation_time) return;
    const interval = window.setInterval(() => {
      setCountdownNow(Date.now());
    }, 1000);
    return () => window.clearInterval(interval);
  }, [status?.is_running, status?.next_evaluation_time]);

  useEffect(() => {
    registerInitHandler(handleInit);
    registerThemeHandler((theme, fonts) => applyTheme(theme, fonts));
    registerSuggestionHandlers(
      (suggestion) => {
        setSuggestions((current) => [
          suggestion,
          ...current.filter((item) => item.suggestion_id !== suggestion.suggestion_id),
        ]);
      },
      (suggestionId) => {
        setSuggestions((current) => current.filter((item) => item.suggestion_id !== suggestionId));
      }
    );
    registerStatusHandler((nextStatus) => {
      applyRuntimeStatus(nextStatus);
    });
    registerModelSelectionHandler((modelId) => {
      selectModel(modelId);
    });
    notifyAmbientPanelReady();
  }, [applyRuntimeStatus, applyTheme, handleInit, selectModel]);

  useLayoutEffect(() => {
    const cardCount = Math.min(suggestions.length, MAX_VISIBLE_CARDS);
    const contentHeight = isEmpty ? EMPTY_HEIGHT : cardCount * CARD_ESTIMATED_HEIGHT + 16;
    requestResize(PANEL_WIDTH, HEADER_HEIGHT + contentHeight);
  }, [isEmpty, suggestions.length, status?.is_running, status?.is_evaluating, models.length]);

  const capabilityLabel = (capability: AmbientSuggestion['capability']) => (
    capability === 'agent_task' ? 'Paprika' : 'Dill'
  );

  const confidenceLabel = (confidence: number) => `${Math.round(confidence * 100)}%`;

  const toggleCollapsed = useCallback(() => {
    const compactSize = isCollapsed ? undefined : measureCollapsedPanelSize(headerRef.current);
    setIsCollapsed((current) => !current);
    toggleCollapsePanel(compactSize);
  }, [isCollapsed]);

  useCollapseShortcut(toggleCollapsed);

  return (
    <div className="basil-webkit-window-frame">
      <section className={`${isContentCollapsed ? 'ambient-panel collapsed' : 'ambient-panel'} basil-webkit-window-surface`}>
      <header className="ambient-header" ref={headerRef}>
        <div className="ambient-header-left" data-ambient-header-left>
          <button className="ambient-header-btn" onClick={dismissPanel} aria-label="Close Proactive Suggestions">
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <button className="ambient-header-btn" onClick={minimizePanel} aria-label="Minimize Proactive Suggestions">
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="7" y1="12.5" x2="15" y2="12.5" stroke="var(--secondary)" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
          <button
            className="ambient-header-btn"
            onClick={toggleCollapsed}
            aria-label={isCollapsed ? 'Expand Proactive Suggestions' : 'Collapse Proactive Suggestions'}
          >
            <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <polyline
                points={isCollapsed ? '7.5,12.5 11,9 14.5,12.5' : '7.5,9.5 11,13 14.5,9.5'}
                fill="none"
                stroke="var(--secondary)"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <div className="ambient-header-title">
            <span>Proactive Suggestions</span>
            {!isEmpty ? <span className="ambient-header-count">{suggestions.length}</span> : null}
          </div>
        </div>
      </header>
      <div className="ambient-controls">
        <span className={status?.is_running ? 'ambient-status running' : 'ambient-status'}>
          {isHydrating ? 'Loading' : status?.is_evaluating ? 'Evaluating' : status?.is_running ? 'Running' : 'Stopped'}
        </span>
        <div className="ambient-model-picker">
          <button
            ref={modelPickerButtonRef}
            type="button"
            className="ambient-picker-button"
            disabled={isBusy || models.length === 0}
            onClick={showNativeModelPicker}
            aria-haspopup="menu"
          >
            <span>{selectedModelLabel}</span>
            <span className="ambient-picker-chevron">v</span>
          </button>
        </div>
        <div className="ambient-frequency-control" aria-label="Capture frequency">
          <button type="button" disabled={isBusy} onClick={() => stepFrequencySeconds(-1)} aria-label="Decrease capture frequency">-</button>
          <input
            inputMode="numeric"
            pattern="[0-9]*"
            value={draftFrequencySeconds}
            disabled={isBusy}
            onFocus={() => setIsEditingFrequency(true)}
            onChange={(event) => setDraftFrequencySeconds(event.target.value)}
            onBlur={() => commitFrequencySeconds(draftFrequencySeconds)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                event.currentTarget.blur();
              }
            }}
            aria-label="Capture frequency in seconds"
          />
          <button type="button" disabled={isBusy} onClick={() => stepFrequencySeconds(1)} aria-label="Increase capture frequency">+</button>
        </div>
        <button
          className={`ambient-runtime-button ${status?.is_running ? 'running' : ''}`}
          disabled={!canToggleRuntime}
          onClick={toggleRuntime}
          title={!status?.enabled ? 'Enable Proactive Suggestions in Settings first' : !hasValidSelectedModel ? 'Choose an evaluator model from the list first' : undefined}
        >
          {status?.is_running ? 'Stop' : 'Start'}
        </button>
      </div>
      <div className="ambient-status-detail">
        <span className={status?.is_evaluating ? 'ambient-pulse active' : 'ambient-pulse'} />
        <span>
          {status?.is_evaluating
            ? 'Checking current context now'
            : nextEvaluationSeconds !== null && status?.is_running
              ? `Next check in ${nextEvaluationSeconds}s`
              : formatLastEvaluation(status?.last_evaluation_completed_at)}
        </span>
        {status?.last_status_message ? <span className="ambient-status-message">{status.last_status_message}</span> : null}
        {modelLoadError ? <span className="ambient-status-message">{modelLoadError}</span> : null}
        {panelMessage ? <span className="ambient-status-message">{panelMessage}</span> : null}
      </div>
      <main className="ambient-body">
        {isEmpty ? (
          <div className="ambient-empty">No suggestions right now.</div>
        ) : (
          suggestions.map((suggestion) => (
            <article className="ambient-card" key={suggestion.suggestion_id}>
              <div className="ambient-card-title">
                <h3>{plainMarkdownText(suggestion.title)}</h3>
                <div className="ambient-card-tags">
                  <span className="ambient-meta">
                    {suggestion.suggestion_type.replace(/_/g, ' ')} - {confidenceLabel(suggestion.confidence)}
                  </span>
                  <span className="ambient-capability-pill">{capabilityLabel(suggestion.capability)}</span>
                </div>
              </div>
              <div className="ambient-card-main">
                <div className="ambient-card-copy">
                  <div className="ambient-provenance">
                    {compactProvenance(suggestion.app_name, suggestion.window_title)}
                  </div>
                  <p className="ambient-card-summary">{plainMarkdownText(suggestion.summary)}</p>
                  {suggestion.proposed_request ? (
                    <p className="ambient-proposed-request">
                      <span>Will ask:</span> {suggestion.proposed_request}
                    </p>
                  ) : null}
                </div>
                <div className="ambient-actions">
                  <button onClick={() => rejectSuggestion(suggestion.suggestion_id)}>
                    Reject
                  </button>
                  <button className="primary" onClick={() => acceptSuggestion(suggestion.suggestion_id)}>
                    Play
                  </button>
                </div>
              </div>
              {suggestion.details ? (
                <details className="ambient-details">
                  <summary>Details</summary>
                  <p>{plainMarkdownText(suggestion.details)}</p>
                </details>
              ) : null}
            </article>
          ))
        )}
      </main>
      </section>
    </div>
  );
}
