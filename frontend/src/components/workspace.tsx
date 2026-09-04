"use client";

import { useEffect, useRef, useState } from "react";
import type { MethodId } from "@/lib/contracts";
import { EXAMPLE_NAME, EXAMPLE_SEQUENCE } from "@/lib/examples";
import { trapDialogFocus } from "@/lib/focus";
import { useWorkspace } from "@/lib/use-workspace";
import { FuzDropImportDialog } from "./fuzdrop-import-dialog";
import { Icon } from "./icons";
import { ResultsWorkspace } from "./results";
import { AnalysisHistory } from "./analysis-history";

type HelpPanel = "documentation" | "about" | "history" | null;

export function Workspace({ testMode = false }: { testMode?: boolean }) {
  const workspace = useWorkspace();
  const [importOpen, setImportOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [help, setHelp] = useState<HelpPanel>(null);
  const [dark, setDark] = useState(false);
  const helpRef = useRef<HTMLDialogElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const methods = workspace.methods;
  const available = (method: MethodId) => methods.find((item) => item.id === method);
  const official = available("fuzdrop")?.official_site_url;
  const officialUrl = official && /^https:\/\/fuzdrop\.bio\.unipd\.it(?:\/|$)/.test(official)
    ? official : "https://fuzdrop.bio.unipd.it/predictor";
  const validation = workspace.validation;
  const validImport = workspace.importState === "valid" ? workspace.imported : null;
  const importedStatus = validImport ? "Imported" : workspace.importState === "sequence_mismatch"
    ? "Sequence mismatch" : workspace.importState === "expired" ? "Expired"
      : workspace.importState === "invalid" ? "Invalid" : "Not imported";

  useEffect(() => {
    if (help && !helpRef.current?.open) helpRef.current?.showModal();
    if (!help && helpRef.current?.open) helpRef.current.close();
  }, [help]);

  useEffect(() => {
    if (!sidebarOpen) return;
    const media = window.matchMedia("(max-width: 1100px)");
    const drawer = sidebarRef.current;
    if (!media.matches || !drawer) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const background = [document.querySelector<HTMLElement>(".topbar"), document.getElementById("workspace-main")];
    const previousInert = background.map((element) => element?.inert ?? false);
    background.forEach((element) => { if (element) element.inert = true; });
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
    drawer.querySelector<HTMLInputElement>("#sequence-name")?.focus();
    const closeOnResize = () => { if (!media.matches) setSidebarOpen(false); };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setSidebarOpen(false); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>("a[href], button, input, textarea, [tabindex]"))
        .filter((element) => !element.matches(":disabled, [tabindex='-1']") && element.getClientRects().length > 0);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    media.addEventListener("change", closeOnResize);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      media.removeEventListener("change", closeOnResize);
      drawer.removeAttribute("role"); drawer.removeAttribute("aria-modal");
      background.forEach((element, index) => { if (element) element.inert = previousInert[index]; });
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected && !drawer.contains(previousFocus)) previousFocus.focus();
      else document.getElementById("workspace-main")?.focus();
    };
  }, [sidebarOpen]);

  function toggleTheme() {
    const next = !dark;
    document.documentElement.dataset.theme = next ? "dark" : "light";
    setDark(next);
  }

  function pasteExample() {
    workspace.setRawSequence(`>${EXAMPLE_NAME}\n${EXAMPLE_SEQUENCE}`);
    workspace.setSequenceName(null);
    setSidebarOpen(window.matchMedia("(max-width: 1100px)").matches);
    setHelp(null);
  }

  function changeSequence(value: string) {
    setImportOpen(false);
    workspace.setRawSequence(value);
  }

  function openImport() {
    if (!validation.valid) {
      setSidebarOpen(true);
      window.requestAnimationFrame(() => document.getElementById("sequence-input")?.focus());
      return;
    }
    setImportOpen(true);
    setSidebarOpen(false);
  }

  return (
    <div className="application-shell">
      <a className="skip-link" href="#workspace-main">Skip to analysis results</a>
      <header className="topbar">
        <a className="brand" href="#workspace-main" aria-label="LLPS Explorer analysis workspace">
          <span className="brand-mark"><Icon name="sequence" width="27" height="27" /></span>
          <span><strong>LLPS <span>Explorer</span></strong><small>Sequence-based Phase Separation Prediction &amp; Interpretation</small></span>
        </a>
        <nav aria-label="Main navigation" className="topnav">
          <a href="#workspace-main" aria-current="page">Analysis</a>
          <button type="button" onClick={pasteExample}>Examples</button>
          <button type="button" onClick={() => setHelp("documentation")}>Documentation</button>
          <button type="button" onClick={() => setHelp("about")}>About</button>
        </nav>
        <div className="topbar-actions">
          <button type="button" className="nav-action" aria-label="History" disabled={!workspace.sessionReady}
            onClick={() => { setHelp("history"); void workspace.refreshHistory(); }}><Icon name="history" /> <span>History</span></button>
          <span className="nav-divider" />
          <button type="button" className="icon-button theme-toggle" onClick={toggleTheme}
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
            <Icon name={dark ? "sun" : "moon"} />
          </button>
        </div>
      </header>

      <div className="workspace-layout">
        {sidebarOpen && <button type="button" tabIndex={-1} className="sidebar-scrim" aria-label="Close analysis setup" onClick={() => setSidebarOpen(false)} />}
        <aside ref={sidebarRef} id="analysis-setup" className={`analysis-sidebar ${sidebarOpen ? "is-open" : ""}`} aria-label="Analysis setup">
          <div className="sidebar-title"><Icon name="settings" /><h2>Analysis setup</h2>
            <button className="icon-button sidebar-close" type="button" aria-label="Close analysis setup" onClick={() => setSidebarOpen(false)}><Icon name="close" /></button>
          </div>
          <div className="sidebar-content">
            <section className="setup-section" aria-labelledby="input-heading">
              <div className="section-heading"><h3 id="input-heading" className="eyebrow">Input</h3><span className="mini-label">Single protein</span></div>
              <label className="field" htmlFor="sequence-name"><span className="field-label">Sequence name <span className="mini-label">optional</span></span>
                <input id="sequence-name" className="input" placeholder="e.g. Protein of interest" value={workspace.sequenceName}
                  onChange={(event) => workspace.setSequenceName(event.target.value)} maxLength={128} autoComplete="off" />
              </label>
              <div className="sequence-field">
                <label className="field-label" htmlFor="sequence-input">Protein sequence <span className="mini-label">FASTA or raw</span></label>
                <textarea id="sequence-input" className="textarea sequence-input" spellCheck={false} autoComplete="off"
                  placeholder={">Protein_name\nPaste your amino-acid sequence here"}
                  value={workspace.rawSequence} onChange={(event) => changeSequence(event.target.value)}
                  aria-invalid={Boolean(workspace.rawSequence && validation.error)} aria-describedby="sequence-validation" />
                <div className="input-actions">
                  <button className="text-button" type="button" onClick={pasteExample}>Paste example <Icon name="arrow" width="13" height="13" /></button>
                  <button className="text-button muted" type="button" onClick={() => changeSequence("")}>Clear</button>
                </div>
              </div>
              <div className="sequence-stats" aria-label="Sequence validation statistics">
                <span>Length <strong>{validation.length} <small>aa</small></strong></span>
                <span>Valid residues <strong>{validation.validResidues}</strong></span>
                <span>Input type <strong>{workspace.rawSequence ? (validation.inputType === "fasta" ? "FASTA" : "Raw") : "—"}</strong></span>
              </div>
              <p id="sequence-validation" className={`validation-message ${validation.error && workspace.rawSequence ? "invalid" : validation.valid ? "valid" : ""}`} aria-live="polite">
                {validation.valid ? <><Icon name="check" width="14" height="14" />Sequence is valid</> : workspace.rawSequence && validation.error ? validation.error.message : "Standard 20 amino acids · one sequence per analysis"}
              </p>
            </section>

            <section className="setup-section" aria-labelledby="automatic-heading">
              <div className="section-heading"><h3 id="automatic-heading" className="eyebrow">Automatic analysis</h3>
                <button className="icon-button compact" type="button" aria-label="Refresh method availability" onClick={() => void workspace.refreshMethods()} disabled={workspace.methodsLoading}><Icon name="refresh" width="14" height="14" /></button>
              </div>
              {workspace.methodsLoading && <p className="muted small" role="status">Checking method availability…</p>}
              {(["lreca", "seg"] as const).map((id) => {
                const descriptor = available(id);
                const ready = Boolean(descriptor?.automatic_analysis_available);
                return <label key={id} className={`method-option ${ready && workspace.selectedAutomatic.includes(id) ? "is-selected" : ""}`} data-method={id}>
                  <input type="checkbox" checked={ready && workspace.selectedAutomatic.includes(id)} disabled={!ready || workspace.submitting}
                    onChange={(event) => workspace.setAutomatic(id, event.target.checked)} />
                  <span className="method-copy"><span className="method-name">{id === "lreca" ? "LRECA" : "SEG / LCR"}</span>
                    <small>{id === "lreca" ? "Human-specific model" : "Low-complexity regions"}</small></span>
                  <span className="badge" data-tone={ready ? id : "neutral"}>{ready ? "Automatic" : workspace.methodsLoading ? "Checking" : "Unavailable"}</span>
                </label>;
              })}
            </section>

            <section className="setup-section" aria-labelledby="external-heading">
              <h3 id="external-heading" className="eyebrow">External result</h3>
              <div className="external-method">
                <div className="method-topline"><strong className="method-title" data-tone="fuzdrop">FuzDrop</strong><span className="badge" data-tone={validImport ? "fuzdrop" : "neutral"}>{validImport ? "Imported" : "Import required"}</span></div>
                <p className="muted small">Official prediction service</p>
                <p className="import-status" aria-live="polite"><span className={`status-dot ${validImport ? "ready" : ""}`} />{importedStatus}
                  {validImport?.raw_score != null && <strong className="mono">pLLPS {validImport.raw_score.toFixed(3)}</strong>}</p>
                {workspace.importError && <p className="small validation-message invalid">{workspace.importError}</p>}
                <button type="button" className="button full-width import-button" onClick={openImport}
                  disabled={!validation.valid || !available("fuzdrop")?.manual_import_available}>
                  <Icon name="upload" width="15" height="15" />{validImport ? "Replace FuzDrop result" : "Import FuzDrop result"}
                </button>
                <div className="external-links"><a href={officialUrl} target="_blank" rel="noopener noreferrer">Open official FuzDrop <Icon name="external" width="12" height="12" /></a>
                  {workspace.imported && <button type="button" className="text-button" onClick={workspace.removeImported}>Remove</button>}</div>
                {validImport && <label className="use-import"><input type="checkbox" role="switch" checked={workspace.useFuzDrop}
                  onChange={(event) => workspace.setUseFuzDrop(event.target.checked)} />Use FuzDrop in this analysis</label>}
              </div>
            </section>

            <section className="setup-section unavailable-section" aria-labelledby="unavailable-heading">
              <h3 id="unavailable-heading" className="eyebrow">Unavailable</h3>
              <div className="blocked-method"><div className="method-topline"><strong>DisMeta / IDR</strong><span className="badge" data-tone="neutral">Unavailable</span></div>
                <p className="small muted">Intrinsically disordered regions</p><p className="small muted">Integration currently unavailable.</p>
                <button type="button" disabled className="blocked-action">Analysis unavailable</button>
              </div>
            </section>

            <section className="setup-section prediction-setup" aria-labelledby="mode-heading">
              <h3 id="mode-heading" className="eyebrow">Prediction mode</h3>
              <fieldset className="mode-switch"><legend className="sr-only">Prediction mode</legend>
                <label className={workspace.mode === "independent" ? "selected" : ""}><input type="radio" name="prediction-mode" value="independent"
                  checked={workspace.mode === "independent"} onChange={() => workspace.setMode("independent")} />Independent</label>
                <label className={`${workspace.mode === "weighted" ? "selected" : ""} ${workspace.weightedDisabledReason ? "disabled" : ""}`}><input type="radio" name="prediction-mode" value="weighted"
                  checked={workspace.mode === "weighted"} disabled={Boolean(workspace.weightedDisabledReason)} onChange={() => workspace.setMode("weighted")}
                  aria-describedby="weighted-explanation" />Weighted</label>
              </fieldset>
              <p className="small muted mode-explanation" id="weighted-explanation">{workspace.weightedDisabledReason || "Compare methods independently, or combine their global scores."}</p>
              {workspace.mode === "weighted" && <div className="weight-editor">
                {(["lreca", "fuzdrop"] as const).map((id) => {
                  const value = id === "lreca" ? workspace.lrecaPercent : 100 - workspace.lrecaPercent;
                  const change = (next: number) => { if (Number.isFinite(next)) workspace.setLrecaPercent(id === "lreca" ? next : 100 - next); };
                  return <div className="weight-row" key={id} data-tone={id}>
                    <div><label htmlFor={`${id}-weight`}>{id === "lreca" ? "LRECA" : "FuzDrop"}</label>
                      <span className="percent-input"><input aria-label={`${id === "lreca" ? "LRECA" : "FuzDrop"} weight (%)`} type="number" min="0" max="100" step="1" value={value} onChange={(event) => change(event.target.valueAsNumber)} /><span>%</span></span></div>
                    <input id={`${id}-weight`} type="range" min="0" max="100" step="1" value={value} onChange={(event) => change(Number(event.target.value))} />
                  </div>;
                })}
                <div className="weight-total"><span>Total <strong>100%</strong></span><button type="button" className="text-button" onClick={() => workspace.setLrecaPercent(50)}>Equal weights</button></div>
                <div className="notice compact"><strong>Experimental weighted score</strong><p>Scores are combined without cross-method probability calibration.</p></div>
              </div>}
            </section>
          </div>
          <div className="run-area">
            <button type="button" className="button primary run-button" disabled={!workspace.canRun || workspace.submitting || workspace.polling}
              onClick={() => { void workspace.run(); setSidebarOpen(false); }}>
              {workspace.submitting ? "Starting analysis…" : workspace.polling ? "Analysis running…" : "Run analysis"}<Icon name="arrow" />
            </button>
            <p className="run-hint">{workspace.runDisabledReason || "Methods run independently. Results retain their provenance."}</p>
          </div>
        </aside>

        <main id="workspace-main" className="workspace-main" tabIndex={-1}>
          {testMode && <div className="feature-test-banner" role="note"><strong>Synthetic test data · Test environment</strong><p>This isolated acceptance environment may include synthetic FuzDrop imports. Test fixtures are not official predictions or biological evidence.</p></div>}
          <div className="workspace-heading">
            <div><div className="breadcrumb">Workspace <span>/</span> Analysis</div><h1>Analysis workspace</h1><p>Explore sequence-based predictions, evidence, and annotations.</p></div>
            <div className="workspace-heading-actions"><button type="button" className="button setup-toggle" aria-expanded={sidebarOpen} aria-controls="analysis-setup" onClick={() => setSidebarOpen(!sidebarOpen)}><Icon name="settings" />Analysis setup</button>
              <span className="connection-status"><span className={`status-dot ${methods.length ? "ready" : ""}`} />{workspace.methodsLoading ? "Connecting" : methods.length ? "Service connected" : "Service unavailable"}</span>
            </div>
          </div>
          {workspace.error && <div className="notice error-notice" role="alert"><div><strong>{workspace.error.message}</strong><p className="small">{workspace.error.code}</p></div>
            {workspace.job && ["queued", "running"].includes(workspace.job.status) && !workspace.polling && <button className="button" type="button" onClick={() => void workspace.retryPolling()}>Retry status check</button>}</div>}
          {workspace.job && workspace.submittedInput?.canonical !== validation.canonical && <div className="notice info-notice">The input has changed. Results below belong to the submitted sequence; run a new analysis to update them.</div>}
          <ResultsWorkspace job={workspace.job} submittedInput={workspace.submittedInput} imported={validImport} methods={methods}
            sessionRevision={workspace.resultRevision} onImport={openImport} onDownload={workspace.downloadJob} />
          <footer className="workspace-footer"><span>LLPS Explorer <span className="footer-separator">·</span> Sequence-first scientific analysis</span><span>Coordinates: 1-based, inclusive</span></footer>
        </main>
      </div>

      <FuzDropImportDialog key={workspace.inputRevision} open={importOpen} onClose={() => setImportOpen(false)} sequence={validation.canonical}
        onImported={workspace.setImported} officialUrl={officialUrl} testMode={testMode} />
      <dialog ref={helpRef} className={`dialog help-dialog ${help === "history" ? "history-dialog" : ""}`} aria-labelledby="help-title" onKeyDown={trapDialogFocus} onClose={() => setHelp(null)}>
        <div className="dialog-header"><div><p className="eyebrow">LLPS Explorer</p><h2 id="help-title">{help === "history" ? "Analysis history" : help === "about" ? "About this workspace" : "A guide to your analysis"}</h2></div>
          <button className="icon-button" type="button" aria-label="Close dialog" onClick={() => setHelp(null)}><Icon name="close" /></button></div>
        <div className="dialog-body">
          {help === "history" ? <AnalysisHistory page={workspace.history} query={workspace.historyQuery} loading={workspace.historyLoading}
            error={workspace.historyError} action={workspace.historyAction} retentionDays={workspace.retentionDays}
            currentJobId={workspace.job?.job_id ?? null} onLoad={workspace.refreshHistory} onOpen={workspace.viewJob}
            onDelete={workspace.deleteJob} onDownload={workspace.downloadJob} onClose={() => setHelp(null)} />
            : help === "about" ? <><p>LLPS Explorer brings sequence-based phase separation prediction and independent sequence annotations into one research workspace.</p><p>LRECA uses a human-specific model. FuzDrop uses official results you import. SEG identifies low-complexity regions. DisMeta is currently unavailable.</p><p>Analysis sequences are retained for the configured period (currently {workspace.retentionDays} days by default) and can be deleted from History. Complete sequences are not written to application logs. This site never contacts FuzDrop automatically; opening the official site is always initiated by you.</p><div className="notice">Prediction results are computational estimates and should be interpreted alongside experimental evidence. Weighted scores have not undergone cross-method probability calibration.</div></> : <div className="help-steps"><section><h3>1. Add a sequence</h3><p>Paste one protein as raw amino-acid text or FASTA. Whitespace is removed and letters are normalized to uppercase. Unsupported residues are reported, never replaced.</p></section><section><h3>2. Choose your evidence</h3><p>LRECA and SEG run automatically when available. For FuzDrop, open its official service yourself, then import its result for the same sequence. Explicitly enable the import to include it. DisMeta remains unavailable.</p></section><section><h3>3. Compare with care</h3><p>Independent mode preserves each method&apos;s score and labels. Weighted mode requires both prediction sources and returns an experimental combined score from the backend.</p></section><section><h3>4. Inspect and save</h3><p>Use the method tabs and tables to inspect results. Positions are 1-based and inclusive. Download backend-generated JSON, CSV, or FASTA files, and use both viewers to inspect aligned evidence and cross-linked residues or regions.</p></section><section><h3>5. Privacy and retention</h3><p>Sequences are retained for the configured period, currently {workspace.retentionDays} days by default. Delete an analysis from History when it is no longer needed. Complete sequences are excluded from application logs. FuzDrop is contacted only when you choose to open its official site.</p></section><div className="notice">Prediction results are computational estimates and should be interpreted alongside experimental evidence.</div></div>}
        </div><div className="dialog-footer"><button type="button" className="button primary" onClick={() => setHelp(null)}>Done</button></div>
      </dialog>
    </div>
  );
}
