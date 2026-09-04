"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { ApiError, importFuzDrop } from "../lib/api";
import type { FuzDropImportResponse } from "../lib/contracts";
import { trapDialogFocus } from "../lib/focus";
import {
  createFuzDropImportPayload,
  decodeFuzDropFile,
  FUZDROP_IMPORT_MAX_BYTES,
  FuzDropFormError,
  officialFuzDropUrl,
} from "../lib/fuzdrop-form";
import type { FuzDropFormValues } from "../lib/fuzdrop-form";

export interface FuzDropImportDialogProps {
  open: boolean;
  onClose: () => void;
  sequence: string;
  onImported: (
    result: FuzDropImportResponse,
  ) => boolean | void | Promise<boolean | void>;
  officialUrl?: string;
  testMode?: boolean;
}

type TSVField = "scoresTSV" | "regionsTSV";
type ImportMessage = { code: string; message: string };
const EMPTY_FORM: FuzDropFormValues = {
  pLLPS: "", scoresTSV: "", regionsTSV: "", officialSource: false, oneBasedInclusive: false,
};

function publicImportError(error: unknown): ImportMessage {
  if (error instanceof ApiError || error instanceof FuzDropFormError) {
    return { code: error.code, message: error.message };
  }
  return {
    code: "FUZDROP_IMPORT_FAILED",
    message: "The import could not be completed. Check your connection and try again.",
  };
}

export function FuzDropImportDialog(props: FuzDropImportDialogProps) {
  // Closing unmounts the session, so reopening starts with fresh declarations and data.
  return props.open ? <FuzDropImportSession {...props} /> : null;
}

function FuzDropImportSession({
  open, onClose, sequence, onImported, officialUrl, testMode = false,
}: FuzDropImportDialogProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const initialFocusRef = useRef<HTMLButtonElement>(null);
  const doneRef = useRef<HTMLButtonElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const fileGeneration = useRef({ scoresTSV: 0, regionsTSV: 0 });
  const [sessionSequence] = useState(sequence);
  const [values, setValues] = useState<FuzDropFormValues>({ ...EMPTY_FORM });
  const [error, setError] = useState<ImportMessage | null>(null);
  const [pending, setPending] = useState(false);
  const [reading, setReading] = useState({ scoresTSV: false, regionsTSV: false });
  const [imported, setImported] = useState<FuzDropImportResponse | null>(null);
  const [copyMessage, setCopyMessage] = useState("");
  const sequenceChanged = sequence !== sessionSequence;
  const validSequence = /^[ACDEFGHIKLMNPQRSTVWY]+$/.test(sequence);
  const busy = pending || reading.scoresTSV || reading.regionsTSV;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const generations = fileGeneration.current;
    const returnFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    if (!dialog.open) dialog.showModal();
    initialFocusRef.current?.focus();
    return () => {
      requestRef.current?.abort();
      generations.scoresTSV += 1;
      generations.regionsTSV += 1;
      if (dialog.open) dialog.close();
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, []);

  useEffect(() => {
    if (open && sequence !== sessionSequence) {
      requestRef.current?.abort();
      onClose();
    }
  }, [open, sequence, sessionSequence, onClose]);

  useEffect(() => {
    if (imported) doneRef.current?.focus();
  }, [imported]);

  function closeDialog() {
    requestRef.current?.abort();
    fileGeneration.current.scoresTSV += 1;
    fileGeneration.current.regionsTSV += 1;
    dialogRef.current?.close();
    onClose();
  }

  function updateField(field: TSVField, text: string) {
    fileGeneration.current[field] += 1;
    setReading((current) => ({ ...current, [field]: false }));
    setValues((current) => ({ ...current, [field]: text }));
    setError(null);
  }

  async function loadFile(field: TSVField, event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    const generation = ++fileGeneration.current[field];
    setError(null);
    setReading((current) => ({ ...current, [field]: true }));
    try {
      if (file.size > FUZDROP_IMPORT_MAX_BYTES) {
        throw new FuzDropFormError(
          "FUZDROP_IMPORT_TOO_LARGE", "Choose a TSV file no larger than 5 MiB.",
        );
      }
      const text = decodeFuzDropFile(await file.arrayBuffer());
      if (generation === fileGeneration.current[field] && dialogRef.current?.open) {
        setValues((current) => ({ ...current, [field]: text }));
      }
    } catch (cause) {
      if (generation === fileGeneration.current[field] && dialogRef.current?.open) {
        setError(cause instanceof FuzDropFormError ? publicImportError(cause) : {
          code: "FUZDROP_FILE_READ_FAILED", message: "This file could not be read. Try selecting it again.",
        });
      }
    } finally {
      if (generation === fileGeneration.current[field]) {
        setReading((current) => ({ ...current, [field]: false }));
      }
    }
  }

  async function copySequence() {
    try {
      await navigator.clipboard.writeText(sequence);
      setCopyMessage("Sequence copied. Paste it into the official website yourself.");
    } catch {
      setCopyMessage("Copy was unavailable. Select and copy the sequence from the input panel.");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || sequenceChanged || imported || !open) return;
    setError(null);
    let payload;
    try {
      payload = createFuzDropImportPayload(sequence, values);
    } catch (cause) {
      setError(publicImportError(cause));
      return;
    }
    const controller = new AbortController();
    const receive = onImported;
    requestRef.current?.abort();
    requestRef.current = controller;
    setPending(true);
    try {
      const result = await importFuzDrop(payload, controller.signal);
      if (controller.signal.aborted) return;
      if (result.sequence !== payload.sequence || result.sequence_length !== payload.sequence.length) {
        throw new FuzDropFormError(
          "EXTERNAL_RESULT_SEQUENCE_MISMATCH",
          "The imported FuzDrop result does not match the current sequence.",
        );
      }
      const accepted = await receive(result);
      if (controller.signal.aborted) return;
      if (accepted === false) {
        throw new FuzDropFormError(
          "EXTERNAL_RESULT_SEQUENCE_MISMATCH",
          "The input changed or the result expired. Import again for the current sequence.",
        );
      }
      setImported(result);
    } catch (cause) {
      if (!controller.signal.aborted) setError(publicImportError(cause));
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        if (!controller.signal.aborted) setPending(false);
      }
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog fuzdrop-import-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onKeyDown={trapDialogFocus}
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <div className="dialog-header">
        <div>
          <span className="badge fuzdrop">Manual import</span>
            <h2 id={`${id}-title`}>Import FuzDrop result</h2>
        </div>
        <button
          ref={initialFocusRef} type="button" className="button"
          aria-label="Close FuzDrop import" onClick={closeDialog}
        >Close</button>
      </div>
      {testMode && <div className="feature-test-banner" role="note"><strong>Synthetic test data · Test environment</strong><p>Acceptance fixtures are not official predictions. The normal import contract is unchanged.</p></div>}
      <p id={`${id}-description`} className="muted">
        Paste or upload exports from the official FuzDrop service. The source is your
        declaration; it is not independently verified. No sequence is submitted to that service here.
      </p>
      {imported ? (
        <section aria-label="Import successful" className="notice" role="status">
          <h3>Import successful</h3>
          <p>Sequence match confirmed · {imported.sequence_length} residues</p>
          <p className="muted">Result ID</p>
          <p><code>{imported.result_id}</code></p>
          <p>pLLPS: {imported.raw_score === null ? "Not supplied" : imported.raw_score}</p>
          <p>
            Saved, but not enabled. Turn on “Use FuzDrop in this analysis” when you want to use it.
          </p>
          <button ref={doneRef} type="button" className="button primary" onClick={closeDialog}>Done</button>
        </section>
      ) : (
        <form onSubmit={submit} noValidate aria-busy={busy}>
          <div className="notice">
            <strong>Bound to your current sequence · {sequence.length} residues</strong>
            <p>
              Use exports for this exact sequence and residue order. Editing the sequence invalidates
              its imported result. The server validates the supplied scores and coordinates.
            </p>
            <div className="button-row">
              <button
                type="button" className="button" onClick={copySequence}
                disabled={!validSequence || sequenceChanged}
              >Copy Sequence</button>
              <a
                className="button" href={officialFuzDropUrl(officialUrl)}
                target="_blank" rel="noopener noreferrer"
              >Open Official FuzDrop <span aria-hidden="true">↗</span></a>
            </div>
            <p className="muted" role="status">{copyMessage}</p>
          </div>
          <fieldset disabled={pending || sequenceChanged || !validSequence}>
            <div className="field">
              <label htmlFor={`${id}-pllps`}>Global pLLPS <span className="muted">optional</span></label>
              <input
                id={`${id}-pllps`} className="input" type="text" inputMode="decimal"
                autoComplete="off" placeholder="0 to 1; leave blank if unavailable"
                value={values.pLLPS}
                onChange={(event) => {
                  setValues((current) => ({ ...current, pLLPS: event.target.value }));
                  setError(null);
                }}
              />
            </div>
            <div className="form-grid">
              {([
                ["scoresTSV", "Residue scores TSV", "position · residue · pDP · Sbind"],
                ["regionsTSV", "Regions TSV", "type · start · end"],
              ] as const).map(([field, label, header]) => (
                <div className="field" key={field}>
                  <label htmlFor={`${id}-${field}`}>{label} <span className="muted">optional</span></label>
                  <textarea
                    id={`${id}-${field}`} className="textarea" rows={5} spellCheck={false}
                    autoComplete="off" value={values[field]}
                    onChange={(event) => updateField(field, event.target.value)}
                    placeholder={`Paste the official tab-separated export\nColumns: ${header}`}
                    aria-describedby={`${id}-${field}-hint`}
                  />
                  <label htmlFor={`${id}-${field}-file`} className="muted">Or choose a UTF-8 TSV file</label>
                  <input
                    id={`${id}-${field}-file`} className="input" type="file"
                    aria-label={`${label} file`}
                    accept=".tsv,.txt,text/tab-separated-values,text/plain"
                    onChange={(event) => { void loadFile(field, event); }}
                  />
                  <small id={`${id}-${field}-hint`} className="muted" role="status">
                    {reading[field] ? "Reading file…" : "Original headers and rows are preserved."}
                  </small>
                </div>
              ))}
            </div>
            <p className="muted">Provide at least one value or export. Local limit: 5 MiB total text. The server may apply a lower limit.</p>
            <div className="field">
              <label>
                <input
                  type="checkbox" checked={values.officialSource}
                  onChange={(event) => setValues((current) => ({ ...current, officialSource: event.target.checked }))}
                />{" "}I declare that these values and exports come from the official FuzDrop service.
              </label>
              <label>
                <input
                  type="checkbox" checked={values.oneBasedInclusive}
                  onChange={(event) => setValues((current) => ({ ...current, oneBasedInclusive: event.target.checked }))}
                />{" "}I confirm that coordinates use 1-based inclusive positions for this sequence.
              </label>
            </div>
          </fieldset>
          {error && (
            <div className="notice error" role="alert">
              <strong>{error.code}</strong><p>{error.message}</p>
            </div>
          )}
          <div className="dialog-footer button-row">
            <button type="button" className="button" onClick={closeDialog}>Cancel</button>
            <button
              type="submit" className="button primary"
              disabled={busy || sequenceChanged || !validSequence || !values.officialSource || !values.oneBasedInclusive}
            >{pending ? "Validating…" : "Validate & Import"}</button>
          </div>
        </form>
      )}
    </dialog>
  );
}
