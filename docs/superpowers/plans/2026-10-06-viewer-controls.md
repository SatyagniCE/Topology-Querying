# Circuit viewer controls implementation plan

> **For agentic workers:** Execute inline using superpowers:executing-plans and test-driven-development. User approved the bounded design and explicitly requested implementation without another approval handoff.

**Goal:** Make circuit inspection the dominant view, add usable incremental zoom and expansion, and remove the misleading homepage metric.

**Architecture:** Retain the existing vanilla UI and vis-network graph. Share bounded zoom/fit calculations across graph and schematic controls. Expand the existing panel into a native modal dialog so there is one graph instance, keyboard focus is contained, and Escape restores the original panel.

**Tech stack:** Existing FastAPI/static UI, vis-network, Node built-in tests, existing Python tests and CUA browser verification. No installations.

**Spec:** Approved in-chat design: wider/taller inspector, slimmer facts sidebar, − / + / Fit controls, full-window expansion, remove the “2 graph reps” counter. Preserve both backend views and metadata behavior.

## Global constraints

- Continue in the existing `codex/research-workbench` checkout serving the local app; preserve all prior uncommitted work.
- No schema, embedding, metadata enrichment or classifier changes.
- Graph zoom increments are multiplicative 20%, bounded to 0.08–4×; schematic fit and original size remain available.
- Use native dialog focus handling and Escape dismissal. Return the same panel to its original location on close/navigation.
- Circuit details use remaining viewport height with compact headings and controls; facts and long content scroll inside panels. Library/Query layout remains unchanged.
- Save the already-tested strict Cypher template as a diagnostic example, explicitly not a verified three-stage classifier.

## Review focus

- Repeated expansion, Escape and route changes must not detach or lose the panel.
- Switching NetworkX/Neo4j while expanded must retain functioning controls.
- Zoom before graph/image readiness must be harmless; bounded zoom must not become zero/NaN.
- Query-result graphs need the same controls without stealing the circuit inspector's state.
- Narrow-screen controls and expanded schematics must not overflow the page.

## Task 1: Viewer controls and layout

**Files:** `src/circuit_workbench/static/{app.js,app.css,index.html,viewer-controls.mjs}`, `tests/ui/viewer-controls.test.mjs`.

**Interfaces:** `nextZoomScale(current, direction, min, max)` returns a bounded scale; `fitImageScale(width,height,availableWidth,availableHeight,padding)` fits without upscaling. UI handlers consume these helpers and the existing Network instance.

- [x] Observe missing controls/old dimensions in the browser; add Node behavior tests and confirm they fail before implementation.
- [x] Implement bounded zoom, graph and schematic toolbars, native dialog expansion/restoration, wider inspector and tall viewers; remove the third metric.
- [x] Run Node tests, syntax checks and full Python suite.
- [x] Verify actual desktop/mobile zoom, fit, backend changes, expansion/Escape, schematic and query-result graph in CUA; save screenshot.

## Task 2: Tested query handoff and final verification

**Files:** `docs/queries/three-stage-opamp-candidates.cypher`, `docs/workbench.md`.

- [x] Preserve the tested stricter query and document its zero matches and structural limitations; do not annotate circuits as three-stage.
- [x] Run live smoke checks, request focused independent review, address important findings and update this ledger.

## Execution ledger

User's direct instruction overrides additional approval handoffs. No commits/pushes or fresh checkout are needed for this incremental change; the currently running app loads assets from this checkout.

Pre-flight: the UI consumes the helper exports named above; existing graph backend API and metadata APIs remain unchanged.

Task 1: complete. Node tests failed before the helper module existed, then passed 5/5. Full Python suite: 137 passed, 14 environment-gated tests skipped, one existing Starlette/httpx deprecation warning. At a 1280×900 breakpoint the graph canvas measured 630px tall and panel 969px wide beside a 220px sidebar. Graph zoom advanced 66% → 79% and reversed; expanded panel measured 1246px wide. Neo4j switching and Escape restoration worked while expanded. Schematics zoomed 810px → 972px and 1:1 restored 100%; netlist expansion also worked.

Task 2: complete. Strict query verified again through the actual Cypher UI: zero rows. Existing corpus/sync remained 3,351 indexed, zero pending; live smoke passed NetworkX/Neo4j 40-node/68-edge parity and all retrieval/read-guard checks.

Final review: focused independent read-only review reported one P2 query-result lifecycle issue and no other actionable findings. Reproduced: running a new query then expanding the old graph left the old graph modal over the new zero-row results. `tests/ui/viewer-browser-regression.mjs` failed with dialogOpen/bodyLocked/oldGraphPresent=true and result="0 rows returned". Fixed by restoring/closing the panel and disposing the network before result replacement; the same browser test passed with all three booleans false. Re-ran the full Python suite and Node tests successfully.

Responsive verification: at 390×844, page width 375px (no overflow), graph height 549px; expanded graph dialog 372×826px. Mobile schematic zoom widened the image 278px → 334px while the page stayed 375px wide. Viewport override reset; browser tab retained on circuit 1004. Desktop and mobile screenshots saved in `output/workbench/screenshots/`. No new dependencies, circuit annotations, commits or remote writes.

Follow-up viewport correction: user rejected the fixed/minimum viewer height because it required page scrolling. Added a browser regression that failed at 1280×800 with a 1096px page, then passed after route-scoped flex sizing and compact chrome. Graph canvas is 460px at 1280×800; Graph/Schematic/Netlist also fit 1280×640 and 390×844. Mobile facts are an optional drawer with Escape dismissal. Independent review identified shrinking mobile metadata grid rows: reproduced source panel starting at 543px while Save ended at 1219px. Added a failing metadata-flow regression, replaced those rows with an internally scrolling block flow, and verified source begins after the form at 1244px. Full suite re-run: 137 passed, 14 skipped; Node helper tests 5 passed; syntax/diff checks and live smoke passed. Native 571×999 window also fits with no page overflow. Updated screenshot: `circuit-1004-compact-desktop.jpg`.

Retrieval handoff: documented the actual substring/text/topology/hybrid paths and saved a manually verified read-only hybrid Cypher example. It needs a BGE text-vector parameter and a reference circuit; Neo4j's bounded vector candidates can rank differently from the UI's full-corpus rank fusion. No automatic NL-to-Cypher or classifier was added.
