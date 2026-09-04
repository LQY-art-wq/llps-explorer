import assert from "node:assert/strict";
import test from "node:test";
import {
  createFuzDropImportPayload,
  decodeFuzDropFile,
  FUZDROP_IMPORT_MAX_BYTES,
  FUZDROP_OFFICIAL_URL,
  FuzDropFormError,
  officialFuzDropUrl,
} from "../src/lib/fuzdrop-form.ts";
import type { FuzDropFormValues } from "../src/lib/fuzdrop-form.ts";

// Synthetic format inputs only; these numbers are not official FuzDrop predictions.
const SEQUENCE = "ACDEFGHIKLMNPQRSTVWY";
const DECLARED: FuzDropFormValues = {
  pLLPS: "", scoresTSV: "", regionsTSV: "", officialSource: true, oneBasedInclusive: true,
};

function rejects(values: Partial<FuzDropFormValues>, code: string, sequence = SEQUENCE) {
  assert.throws(
    () => createFuzDropImportPayload(sequence, { ...DECLARED, ...values }),
    (error: unknown) => error instanceof FuzDropFormError && error.code === code,
  );
}

test("empty pLLPS is omitted rather than converted to zero; explicit empty regions survive", () => {
  const regionsTSV = "type\tstart\tend\n";
  const payload = createFuzDropImportPayload(SEQUENCE, {
    ...DECLARED, pLLPS: " \t ", regionsTSV,
  });
  assert.deepEqual(payload, {
    sequence: SEQUENCE,
    source_declaration: "official_fuzdrop_export",
    coordinate_system: "one_based_inclusive",
    regions_tsv: regionsTSV,
  });
  assert.equal("pLLPS" in payload, false);
  assert.equal("scores_tsv" in payload, false);
});

test("an explicit zero pLLPS remains supplied data", () => {
  assert.equal(createFuzDropImportPayload(SEQUENCE, { ...DECLARED, pLLPS: "0" }).pLLPS, 0);
});

test("optional score accepts decimal endpoints and scientific notation", () => {
  for (const [raw, expected] of [[".68", 0.68], ["1", 1], ["1.0e0", 1], ["6.8e-1", 0.68]] as const) {
    assert.equal(createFuzDropImportPayload(SEQUENCE, { ...DECLARED, pLLPS: raw }).pLLPS, expected);
  }
});

test("missing content and missing declarations are rejected independently", () => {
  rejects({ pLLPS: "  ", scoresTSV: "\r\n", regionsTSV: "\t" }, "FUZDROP_IMPORT_CONTENT_REQUIRED");
  rejects({ pLLPS: "0.68", officialSource: false }, "FUZDROP_DECLARATION_REQUIRED");
  rejects({ pLLPS: "0.68", oneBasedInclusive: false }, "FUZDROP_DECLARATION_REQUIRED");
});

test("nonfinite, nondecimal and out-of-range pLLPS cannot become a valid payload", () => {
  for (const raw of ["NaN", "Infinity", "-Infinity", "-0.01", "1.01", "0x1", "0,68", "1_0", "1e999", "text"]) {
    rejects({ pLLPS: raw }, "FUZDROP_INVALID_SCORE");
  }
});

test("exact out-of-range decimals are rejected before boundary rounding can hide them", () => {
  for (const raw of ["-1e-999", "1.00000000000000000001", "1.00000000000000000001e0"]) {
    rejects({ pLLPS: raw }, "FUZDROP_INVALID_SCORE");
  }
  assert.equal(createFuzDropImportPayload(SEQUENCE, {
    ...DECLARED, pLLPS: "0.99999999999999999999",
  }).pLLPS, 1);
});

test("the payload uses the current canonical sequence without client TSV reinterpretation", () => {
  const scoresTSV = "\ufeffposition\tresidue\tpDP\tSbind\r\n1\tA\tundefined\t\r\n";
  const regionsTSV = "type\tstart\tend\nAggregation hot-spot\t2\t3\nAggregation hot-spot\t2\t3\n";
  const payload = createFuzDropImportPayload(SEQUENCE, { ...DECLARED, scoresTSV, regionsTSV });
  assert.equal(payload.sequence, SEQUENCE);
  assert.equal(payload.scores_tsv, scoresTSV);
  assert.equal(payload.regions_tsv, regionsTSV);
  // Full row counts, amino-acid identity and native coordinates remain server validations.
});

test("invalid or unnormalized sequence cannot be attached to an import", () => {
  for (const sequence of ["", "acde", ">example\nACDE", "AC DE", "ACX"]) {
    rejects({ pLLPS: "0.68" }, "FUZDROP_SEQUENCE_REQUIRED", sequence);
  }
});

test("import payload cannot select methods, enable FuzDrop, or set weighted mode", () => {
  const payload = createFuzDropImportPayload(SEQUENCE, { ...DECLARED, pLLPS: "0.68" });
  assert.deepEqual(Object.keys(payload).sort(), [
    "coordinate_system", "pLLPS", "sequence", "source_declaration",
  ]);
});

test("UTF-8 files preserve Unicode, BOM and original CRLF bytes after decoding", () => {
  const source = "\ufeffposition\tresidue\tpDP\tSbind\r\n# 合成格式测试\r\n";
  assert.equal(decodeFuzDropFile(new TextEncoder().encode(source).buffer), source);
});

test("invalid UTF-8, UTF-16 and binary data are rejected without replacement characters", () => {
  for (const bytes of [
    new Uint8Array([0xc3, 0x28]),
    new Uint8Array([0xff, 0xfe, 0x70, 0x00]),
    new Uint8Array([0x70, 0x00, 0x6f, 0x00]),
  ]) {
    assert.throws(
      () => decodeFuzDropFile(bytes.buffer),
      (error: unknown) => error instanceof FuzDropFormError
        && error.code === "FUZDROP_INVALID_FILE_ENCODING",
    );
  }
});

test("file and combined text limits count UTF-8 bytes", () => {
  assert.throws(
    () => decodeFuzDropFile(new ArrayBuffer(FUZDROP_IMPORT_MAX_BYTES + 1)),
    (error: unknown) => error instanceof FuzDropFormError && error.code === "FUZDROP_IMPORT_TOO_LARGE",
  );
  const boundary = "x".repeat(FUZDROP_IMPORT_MAX_BYTES - SEQUENCE.length);
  assert.equal(createFuzDropImportPayload(SEQUENCE, { ...DECLARED, scoresTSV: boundary }).scores_tsv, boundary);
  rejects({ scoresTSV: boundary + "x" }, "FUZDROP_IMPORT_TOO_LARGE");
  rejects({ scoresTSV: "测".repeat(Math.ceil(FUZDROP_IMPORT_MAX_BYTES / 3)) }, "FUZDROP_IMPORT_TOO_LARGE");
});

test("official links use only audited exact HTTPS destinations, with no query or submitted sequence", () => {
  for (const candidate of [
    "https://fuzdrop.bio.unipd.it", "https://fuzdrop.bio.unipd.it/", FUZDROP_OFFICIAL_URL,
  ]) assert.equal(officialFuzDropUrl(candidate), candidate);
  for (const candidate of [
    undefined, "", "https://evil.example/", "javascript:alert(1)",
    "https://fuzdrop.bio.unipd.it.evil.example/predictor",
    "https://fuzdrop.bio.unipd.it/predictor?sequence=ACDE",
    "https://user@fuzdrop.bio.unipd.it/predictor", "http://fuzdrop.bio.unipd.it/predictor",
    "https://fuzdrop.bio.unipd.it/predictor#fragment",
  ]) assert.equal(officialFuzDropUrl(candidate), FUZDROP_OFFICIAL_URL);
});
