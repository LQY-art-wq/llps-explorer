'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  AnalysisExportKind, AnalysisHistoryPage, AnalysisJob, AutomaticMethodId, FuzDropImportResponse,
  InputSnapshot, MethodDescriptor, PredictionMode,
} from './contracts.ts';
import {
  ApiError, deleteAnalysis, friendlyApiError, getAnalysis, getAnalysisExport, getMethods,
  getPublicConfig, isAbortError, listAnalysisHistory, pollAnalysis, submitAnalysis,
} from './api.ts';
import { availableAutomaticMethods, evaluateDraft, IMPORT_MESSAGES, ImportSession, isTerminalJob, snapshotInput } from './analysis-state.ts';
import { DEFAULT_HISTORY_QUERY, lastHistoryOffset, normalizeHistoryQuery, persistedInput } from './history-state.ts';
import type { HistoryQuery } from './history-state.ts';
import { saveAnalysisDownload } from './download.ts';
import { parseSequence } from './sequence.ts';
import { withAnalysisSessionLock } from './session-bootstrap.ts';

export function useWorkspace() {
  const [rawSequence, updateRawSequence] = useState('');
  const rawRef = useRef('');
  const [manualName, updateManualName] = useState<string | null>(null);
  const validation = useMemo(() => parseSequence(rawSequence), [rawSequence]);
  const sequenceName = manualName ?? validation.headerName ?? '';
  const [methods, updateMethods] = useState<MethodDescriptor[]>([]);
  const [methodsLoading, setMethodsLoading] = useState(true);
  const [selectedAutomatic, updateSelectedAutomatic] = useState<AutomaticMethodId[]>([]);
  const defaultsApplied = useRef(false);
  const [session] = useState(() => new ImportSession());
  const [, renderImport] = useState(0);
  const [useFuzDrop, updateUseFuzDrop] = useState(false);
  const [mode, setMode] = useState<PredictionMode>('independent');
  const [lrecaPercent, updateLrecaPercent] = useState(50);
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const jobRef = useRef<AnalysisJob | null>(null);
  const [resultRevision, setResultRevision] = useState(0);
  const [submittedInput, setSubmittedInput] = useState<InputSnapshot | null>(null);
  const [history, setHistory] = useState<AnalysisHistoryPage>({
    items: [], total: 0, limit: DEFAULT_HISTORY_QUERY.limit, offset: DEFAULT_HISTORY_QUERY.offset,
  });
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [historyAction, setHistoryAction] = useState<string | null>(null);
  const [currentHistoryQuery, setCurrentHistoryQuery] = useState<HistoryQuery>(DEFAULT_HISTORY_QUERY);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [polling, setPolling] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [error, setError] = useState<ApiError | null>(null);
  const mounted = useRef(true);
  const catalogAbort = useRef<AbortController | null>(null);
  const historyAbort = useRef<AbortController | null>(null);
  const viewAbort = useRef<AbortController | null>(null);
  const historyEpoch = useRef(0);
  const historyQueryRef = useRef<HistoryQuery>(DEFAULT_HISTORY_QUERY);
  const configAbort = useRef<AbortController | null>(null);
  const analysisAbort = useRef<AbortController | null>(null);
  const analysisEpoch = useRef(0);
  const draft = { rawSequence, sequenceName, methods, selectedAutomatic, imported: session.imported, useFuzDrop, mode, lrecaPercent };
  const assessment = evaluateDraft(draft);
  const refreshHistory = useCallback(async (requested?: Partial<HistoryQuery>) => {
    const query = normalizeHistoryQuery(requested ?? historyQueryRef.current);
    historyQueryRef.current = query; setCurrentHistoryQuery(query);
    historyAbort.current?.abort();
    const controller = new AbortController(); historyAbort.current = controller;
    const epoch = ++historyEpoch.current;
    setHistoryLoading(true); setHistoryError(null);
    try {
      let page = await listAnalysisHistory(query, controller.signal);
      if (page.items.length === 0 && page.total > 0 && page.offset > 0) {
        query.offset = lastHistoryOffset(page.total, page.limit);
        historyQueryRef.current = query; setCurrentHistoryQuery(query);
        page = await listAnalysisHistory(query, controller.signal);
      }
      if (!mounted.current || controller.signal.aborted || epoch !== historyEpoch.current) return;
      setHistory(page);
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && epoch === historyEpoch.current && !isAbortError(failure)) {
        setHistoryError(friendlyApiError(failure));
      }
    } finally {
      if (mounted.current && !controller.signal.aborted && epoch === historyEpoch.current) setHistoryLoading(false);
    }
  }, []);
  const refreshPublicConfig = useCallback(async () => {
    configAbort.current?.abort();
    const controller = new AbortController(); configAbort.current = controller;
    try {
      const config = await getPublicConfig(controller.signal);
      if (mounted.current && !controller.signal.aborted) setRetentionDays(config.analysis_retention_days);
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && !isAbortError(failure)) setRetentionDays(null);
    }
  }, []);
  const refreshMethods = useCallback(async () => {
    catalogAbort.current?.abort();
    const controller = new AbortController(); catalogAbort.current = controller;
    setMethodsLoading(true); setError(null);
    try {
      const result = await getMethods(controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      updateMethods(result);
      if (!defaultsApplied.current) {
        defaultsApplied.current = true;
        updateSelectedAutomatic(availableAutomaticMethods(result));
      }
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && !isAbortError(failure)) {
        updateMethods([]); setError(friendlyApiError(failure));
      }
    } finally {
      if (mounted.current && !controller.signal.aborted) setMethodsLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    const initialLoad = setTimeout(() => {
      void (async () => {
        // Establish the proxy's HttpOnly ownership cookie before any other API call.
        // Concurrent first requests could otherwise each create a different anonymous owner.
        await withAnalysisSessionLock(refreshHistory);
        if (!mounted.current) return;
        setSessionReady(true);
        await Promise.all([refreshMethods(), refreshPublicConfig()]);
      })();
    }, 0);
    return () => {
      clearTimeout(initialLoad);
      mounted.current = false; catalogAbort.current?.abort(); historyAbort.current?.abort();
      viewAbort.current?.abort(); configAbort.current?.abort(); analysisAbort.current?.abort();
      analysisEpoch.current += 1; session.remove();
    };
  }, [refreshHistory, refreshMethods, refreshPublicConfig, session]);
  useEffect(() => {
    if (!session.imported) return;
    const deadline = Date.parse(session.imported.expires_at);
    const timer = setTimeout(() => {
      if (session.expire()) { updateUseFuzDrop(false); renderImport((value) => value + 1); }
    }, Math.min(Math.max(deadline - Date.now() + 1, 1), 2_147_483_647));
    return () => clearTimeout(timer);
  }, [session, session.imported]);

  function setRawSequence(value: string) {
    if (value === rawRef.current) return;
    rawRef.current = value;
    session.invalidate(); updateUseFuzDrop(false);
    updateRawSequence(value); renderImport((revision) => revision + 1);
    if (!value) updateManualName(null);
  }
  function setSequenceName(value: string | null) { updateManualName(value); }
  function setAutomatic(method: AutomaticMethodId, selected: boolean) {
    if (method !== 'lreca' && method !== 'seg') return;
    if (selected && !availableAutomaticMethods(methods).includes(method)) return;
    updateSelectedAutomatic((current) => selected ? [...new Set([...current, method])] : current.filter((id) => id !== method));
  }
  const revision = session.revision;
  async function setImported(result: FuzDropImportResponse): Promise<boolean> {
    if (!mounted.current || revision !== session.revision) return false;
    updateUseFuzDrop(false);
    const accepting = session.accept(result, parseSequence(rawRef.current).canonical, revision);
    renderImport((value) => value + 1);
    const accepted = await accepting;
    if (mounted.current) renderImport((value) => value + 1);
    return accepted;
  }
  function removeImported() {
    session.remove(); updateUseFuzDrop(false); renderImport((value) => value + 1);
  }
  function setUseFuzDrop(enabled: boolean) {
    if (!enabled) { updateUseFuzDrop(false); return; }
    const current = evaluateDraft({ ...draft, imported: session.imported });
    if (current.importState === 'valid' && current.validation.valid && methods.some((method) => method.id === 'fuzdrop' && method.manual_import_available)) updateUseFuzDrop(true);
  }
  function setLrecaPercent(percent: number) {
    // Keep invalid/empty numeric input invalid; never silently normalize a bad weight.
    updateLrecaPercent(percent);
  }
  function replaceJob(next: AnalysisJob | null) {
    jobRef.current = next;
    setJob(next);
  }
  function receiveJob(next: AnalysisJob, input: InputSnapshot, epoch: number) {
    if (!mounted.current || epoch !== analysisEpoch.current) return;
    replaceJob(next);
  }
  async function startPolling(initial: AnalysisJob, input: InputSnapshot, controller: AbortController, epoch: number, immediate = false) {
    if (isTerminalJob(initial)) { setPolling(false); return; }
    setPolling(true);
    try {
      await pollAnalysis({ jobId: initial.job_id, signal: controller.signal, initialJob: initial, immediate,
        onJob: (next) => {
          if (next.sequence.sha256 !== initial.sequence.sha256 || next.sequence.length !== input.length) throw new ApiError('INVALID_RESPONSE');
          receiveJob(next, input, epoch);
        } });
      if (!controller.signal.aborted) void refreshHistory();
    } catch (failure) {
      if (mounted.current && epoch === analysisEpoch.current && !controller.signal.aborted && !isAbortError(failure)) setError(friendlyApiError(failure));
    } finally {
      if (mounted.current && epoch === analysisEpoch.current) setPolling(false);
    }
  }
  async function run() {
    if (submittingRef.current) return;
    const currentDraft = { ...draft, imported: session.imported };
    const current = evaluateDraft(currentDraft);
    if (!current.request) { setError(new ApiError('INVALID_DRAFT')); return; }
    viewAbort.current?.abort(); viewAbort.current = null;
    setHistoryAction((action) => action?.startsWith('open:') ? null : action);
    analysisAbort.current?.abort();
    const controller = new AbortController(); analysisAbort.current = controller;
    const epoch = ++analysisEpoch.current;
    const input = snapshotInput(currentDraft);
    submittingRef.current = true; setSubmitting(true); setPolling(false); setError(null);
    replaceJob(null); setSubmittedInput(input);
    try {
      const next = await submitAnalysis(current.request, controller.signal);
      if (!mounted.current || epoch !== analysisEpoch.current || controller.signal.aborted) return;
      if (next.sequence.length !== input.length) throw new ApiError('INVALID_RESPONSE');
      receiveJob(next, input, epoch);
      void refreshHistory();
      void startPolling(next, input, controller, epoch);
    } catch (failure) {
      if (mounted.current && epoch === analysisEpoch.current && !controller.signal.aborted && !isAbortError(failure)) setError(friendlyApiError(failure));
    } finally {
      if (epoch === analysisEpoch.current) { submittingRef.current = false; if (mounted.current) setSubmitting(false); }
    }
  }
  function retryPolling() {
    if (!job || !submittedInput || isTerminalJob(job) || submittingRef.current) return;
    viewAbort.current?.abort(); viewAbort.current = null;
    setHistoryAction((action) => action?.startsWith('open:') ? null : action);
    analysisAbort.current?.abort();
    const controller = new AbortController(); analysisAbort.current = controller;
    const epoch = ++analysisEpoch.current;
    setError(null); void startPolling(job, submittedInput, controller, epoch, true);
  }
  async function viewJob(jobId: string): Promise<boolean> {
    viewAbort.current?.abort();
    const controller = new AbortController(); viewAbort.current = controller;
    setHistoryAction(`open:${jobId}`); setHistoryError(null);
    try {
      const persisted = await getAnalysis(jobId, controller.signal);
      const input = await persistedInput(persisted);
      if (!input || !mounted.current || controller.signal.aborted || viewAbort.current !== controller) {
        if (!input) throw new ApiError('INVALID_RESPONSE');
        return false;
      }
      // Only a fully validated target may replace and stop the current result.
      analysisAbort.current?.abort();
      const pollingController = new AbortController(); analysisAbort.current = pollingController;
      const epoch = ++analysisEpoch.current;
      submittingRef.current = false; setSubmitting(false); setError(null); setPolling(false);
      replaceJob(persisted); setSubmittedInput(input); setResultRevision((value) => value + 1);
      void startPolling(persisted, input, pollingController, epoch, true);
      return true;
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted && !isAbortError(failure)) setHistoryError(friendlyApiError(failure));
      return false;
    } finally {
      if (mounted.current && !controller.signal.aborted && viewAbort.current === controller) setHistoryAction(null);
    }
  }
  async function deleteJob(jobId: string): Promise<boolean> {
    const controller = new AbortController();
    setHistoryAction(`delete:${jobId}`); setHistoryError(null);
    try {
      await deleteAnalysis(jobId, controller.signal);
      if (!mounted.current) return false;
      setHistory((current) => current.items.some((item) => item.job_id === jobId)
        ? { ...current, items: current.items.filter((item) => item.job_id !== jobId), total: Math.max(0, current.total - 1) }
        : current);
      if (jobRef.current?.job_id === jobId) {
        analysisAbort.current?.abort(); analysisEpoch.current += 1;
        replaceJob(null); setSubmittedInput(null); setPolling(false); setError(null);
      }
      await refreshHistory(historyQueryRef.current);
      return true;
    } catch (failure) {
      if (mounted.current && !isAbortError(failure)) setHistoryError(friendlyApiError(failure));
      return false;
    } finally {
      if (mounted.current) setHistoryAction(null);
    }
  }
  async function downloadJob(jobId: string, kind: AnalysisExportKind): Promise<boolean> {
    const controller = new AbortController();
    setHistoryAction(`download:${jobId}`); setHistoryError(null);
    try {
      saveAnalysisDownload(await getAnalysisExport(jobId, kind, controller.signal));
      return true;
    } catch (failure) {
      if (mounted.current && !isAbortError(failure)) {
        const friendly = friendlyApiError(failure); setHistoryError(friendly); setError(friendly);
      }
      return false;
    } finally {
      if (mounted.current) setHistoryAction(null);
    }
  }
  const runDisabledReason = methodsLoading ? 'Loading method availability.' : submitting ? 'Creating the analysis job.' : assessment.runDisabledReason;
  return {
    rawSequence, setRawSequence, sequenceName, setSequenceName, validation,
    methods, methodsLoading, refreshMethods, selectedAutomatic, setAutomatic,
    imported: session.imported, importState: session.status, setImported, removeImported,
    importError: IMPORT_MESSAGES[session.status], useFuzDrop, setUseFuzDrop, mode, setMode,
    lrecaPercent, setLrecaPercent, weightedDisabledReason: assessment.weightedDisabledReason,
    canRun: runDisabledReason === null, runDisabledReason, run, job, submittedInput,
    polling, error, retryPolling, history, historyLoading, historyError, historyAction,
    refreshHistory, historyQuery: currentHistoryQuery, viewJob, deleteJob, downloadJob, retentionDays,
    resultRevision, inputRevision: session.revision, sessionReady, submitting,
  };
}
