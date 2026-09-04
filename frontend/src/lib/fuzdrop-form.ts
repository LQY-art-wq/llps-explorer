import type { FuzDropImportRequest } from "./contracts";

/** A local upload safeguard; the server remains authoritative about its configured limit. */
export const FUZDROP_IMPORT_MAX_BYTES = 5 * 1024 * 1024;
export const FUZDROP_OFFICIAL_URL = "https://fuzdrop.bio.unipd.it/predictor";

const OFFICIAL_URLS = new Set([
  "https://fuzdrop.bio.unipd.it",
  "https://fuzdrop.bio.unipd.it/",
  FUZDROP_OFFICIAL_URL,
]);

export interface FuzDropFormValues {
  pLLPS: string;
  scoresTSV: string;
  regionsTSV: string;
  officialSource: boolean;
  oneBasedInclusive: boolean;
}

export class FuzDropFormError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "FuzDropFormError";
    this.code = code;
  }
}

export function officialFuzDropUrl(candidate?: string): string {
  return candidate && OFFICIAL_URLS.has(candidate) ? candidate : FUZDROP_OFFICIAL_URL;
}

function parseOptionalScore(raw: string): number | undefined {
  const token = raw.trim();
  if (!token) return undefined;
  const match = /^([+-]?)(\d*\.?\d+|\d+\.)(?:[eE]([+-]?\d+))?$/.exec(token);
  const score = Number(token);
  if (!match || !Number.isFinite(score) || score < 0 || score > 1) {
    throw new FuzDropFormError("FUZDROP_INVALID_SCORE", "pLLPS must be a finite number from 0 to 1.");
  }
  const digits = match[2].replace(".", "").replace(/^0+/, "");
  if (digits && (match[1] === "-" || score === 0)) {
    throw new FuzDropFormError("FUZDROP_INVALID_SCORE", "pLLPS must be a finite number from 0 to 1.");
  }
  // Do not round a decimal just above one into an apparently valid boundary value.
  if (digits && score === 1) {
    const decimals = match[2].split(".")[1]?.length ?? 0;
    const scale = Number(match[3] ?? 0) - decimals;
    const magnitude = digits.length + scale;
    if (magnitude > 1 || (magnitude === 1 && (
      digits[0] > "1" || /[1-9]/.test(digits.slice(1))
    ))) {
      throw new FuzDropFormError("FUZDROP_INVALID_SCORE", "pLLPS must be a finite number from 0 to 1.");
    }
  }
  return score;
}

/** Bind the declared exports to the current canonical sequence, without parsing TSV in the client. */
export function createFuzDropImportPayload(
  sequence: string,
  values: FuzDropFormValues,
): FuzDropImportRequest {
  if (!/^[ACDEFGHIKLMNPQRSTVWY]+$/.test(sequence)) {
    throw new FuzDropFormError(
      "FUZDROP_SEQUENCE_REQUIRED", "Enter a valid protein sequence before importing a result.",
    );
  }
  if (!values.officialSource || !values.oneBasedInclusive) {
    throw new FuzDropFormError(
      "FUZDROP_DECLARATION_REQUIRED", "Confirm the official source and coordinate declarations.",
    );
  }
  const pLLPS = parseOptionalScore(values.pLLPS);
  const scores = values.scoresTSV.trim() ? values.scoresTSV : undefined;
  const regions = values.regionsTSV.trim() ? values.regionsTSV : undefined;
  if (pLLPS === undefined && scores === undefined && regions === undefined) {
    throw new FuzDropFormError(
      "FUZDROP_IMPORT_CONTENT_REQUIRED", "Provide pLLPS, a scores TSV, or a regions TSV.",
    );
  }
  const encoder = new TextEncoder();
  const size = [sequence, scores, regions].reduce(
    (total, text) => total + (text === undefined ? 0 : encoder.encode(text).byteLength), 0,
  );
  if (size > FUZDROP_IMPORT_MAX_BYTES) {
    throw new FuzDropFormError(
      "FUZDROP_IMPORT_TOO_LARGE", "The sequence and TSV text must fit within the 5 MiB upload limit.",
    );
  }
  return {
    sequence,
    source_declaration: "official_fuzdrop_export",
    coordinate_system: "one_based_inclusive",
    ...(pLLPS === undefined ? {} : { pLLPS }),
    ...(scores === undefined ? {} : { scores_tsv: scores }),
    ...(regions === undefined ? {} : { regions_tsv: regions }),
  };
}

/** Preserve BOM/newlines for server provenance, rejecting corrupt or non-UTF-8 uploads. */
export function decodeFuzDropFile(bytes: ArrayBuffer): string {
  if (bytes.byteLength > FUZDROP_IMPORT_MAX_BYTES) {
    throw new FuzDropFormError("FUZDROP_IMPORT_TOO_LARGE", "Choose a TSV file no larger than 5 MiB.");
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new FuzDropFormError(
      "FUZDROP_INVALID_FILE_ENCODING", "This file is not valid UTF-8. Export or save it as UTF-8 TSV.",
    );
  }
  if (text.includes("\0")) {
    throw new FuzDropFormError(
      "FUZDROP_INVALID_FILE_ENCODING", "This file contains binary or UTF-16 data. Use UTF-8 TSV.",
    );
  }
  return text;
}
