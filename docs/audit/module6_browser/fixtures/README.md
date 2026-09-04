# Module 6 browser fixtures — synthetic FuzDrop values only

**These are test inputs, not official FuzDrop predictions or service responses.**
The 248-aa sequence is the real `human_positive_line_1` sequence from the frozen
LRECA baseline. Every FuzDrop pLLPS, pDP, Sbind value and region here is deliberately
invented for frontend/API validation. They do not validate prediction accuracy,
biological activity, official origin, native coordinates, or score calibration.

For the browser import scenario:

1. Paste [human_positive_line_1.fasta](human_positive_line_1.fasta) into the workspace.
2. Open the FuzDrop import dialog. In this explicit test scenario, acknowledge the
   source and 1-based-inclusive coordinate declarations required by the existing API.
   The source declaration exercises the contract; it does not make this synthetic
   fixture an authentic official result.
3. Upload or paste [synthetic_fuzdrop_scores_248aa.tsv](synthetic_fuzdrop_scores_248aa.tsv)
   and [synthetic_fuzdrop_regions_248aa.tsv](synthetic_fuzdrop_regions_248aa.tsv).
4. Enter the **synthetic pLLPS value `0.68`**, then validate/import.
5. Explicitly enable “Use FuzDrop in this analysis” if the scenario calls for it.
   Importing alone must not select FuzDrop or change the prediction mode.

[synthetic_fuzdrop_import_248aa.json](synthetic_fuzdrop_import_248aa.json) contains
the exact request body for reproducing this software-only import through the API.
It contains no `result_id`, fabricated job response, or predicted LRECA/SEG output.
The running backend issues the actual import ID and expiry time.

The fixture contains 248 score rows and 3 arbitrary region rows. Column names and
region labels follow the already audited import contract. Local validation used
the existing `FuzDropImportRequest` and `import_fuzdrop_result`; no server, model,
external request, or dependency installation was needed to generate these files.
Sequence identity and file hashes are recorded in [fixture_manifest.json](fixture_manifest.json).

For the separate partial-success browser scenario, the explicitly gated
`scripts/module6_test_backend.py --fail-seg` entry point keeps real LRECA inference,
real SEG load/health checks, and the existing orchestrator. It makes only SEG analysis
raise `Module6InjectedSEGFailure`; the normal public method error remains
`METHOD_EXECUTION_FAILED`. With a successful real LRECA result, the job is
`partial_success`. This test entry point is never part of production startup.
