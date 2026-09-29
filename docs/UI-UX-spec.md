# Analytica Workbench — UI/UX Specification

**Document type:** Product interface and interaction specification  
**Scope:** Browser application in `frontend/`  
**Status:** Living source-of-truth  
**Baseline:** Current Data, Prepare, Explore, Analyze, supervised Model, and Results implementation
**Last reviewed:** 2026-09-29

---

## 1. Interface objective

Analytica Workbench shall present advanced data analysis as one coherent professional workspace rather than a collection of disconnected tools.

The interface must optimize for four qualities:

1. **Analytical clarity** — values, assumptions, version context and result meaning take priority over decoration.
2. **Progressive disclosure** — controls appear when relevant to the current analytical task.
3. **Reproducibility visibility** — the selected dataset version and transformation lineage remain visible and understandable.
4. **Low-friction depth** — common tasks should require little configuration, while advanced statistical information remains inspectable.

The target visual character is restrained, modern, precise and product-like. Glass/translucent materials are used for navigation/control chrome, not for dense tables, charts or statistical results where transparency would reduce legibility.

---

# 2. Information architecture

The primary workflow is fixed:

`Data → Prepare → Explore → Analyze → Model → Results`

The workflow appears in the primary navigation in that order. The order communicates analytical progression, but users are not forced through a destructive wizard.

## 2.1 Stage responsibilities

### Data
Purpose: import, ingestion status, profile, quality summary, schema inspection and raw canonical preview.

### Prepare
Purpose: create reproducible transformations. This is the principal dataset-mutation stage.

### Explore
Purpose: understand individual variables and relationships without changing the dataset.

### Analyze
Purpose: answer inferential statistical questions through guided test selection and evidence-rich results.

### Model
Purpose: configure targets/features, preprocessing, training, validation, comparison and model diagnostics.

### Results
Purpose: gather saved analytical/model outputs, compose reports and export reproducible artifacts.

## 2.2 Availability rules

- `Data` is always available.
- `Prepare`, `Explore`, `Analyze`, `Model`, and `Results` become available after a ready dataset version exists.
- Disabled future stages must look intentionally unavailable, not broken.
- Changing the selected dataset version changes the source of truth for Explore and Analyze.
- Version-sensitive workspaces must reset stale state when the selected version changes.

---

# 3. Application shell

## 3.1 Desktop shell

The current desktop shell uses a two-column application frame:

- fixed/sticky navigation rail: `188px`;
- main workspace: remaining width;
- outer gap: `14px`;
- outer padding: `14px`.

The shell should fill at least the viewport height.

## 3.2 Navigation rail

The navigation rail shall contain:

1. Analytica brand mark and `Analytica / Workbench` lockup;
2. numbered workflow stages;
3. active-stage treatment;
4. disabled treatment for unavailable stages;
5. workspace status at the bottom.

Current stage indexes use small numeric labels (`01`, `02`, etc.) to support fast scanning without competing with stage names.

The active item shall use a subtle elevated/solid treatment inside the glass navigation surface. Hover may increase background contrast but should not produce large motion.

## 3.3 Toolbar

The top toolbar shall remain sticky on desktop and include:

- current workspace label (`Analytica Workbench · <Stage>`);
- current analysis/dataset title;
- selected dataset version when available;
- Import Data action;
- New Analysis action when a dataset is loaded.

The toolbar is control chrome and may use translucent/glass material.

## 3.4 Glass-material rule

Translucency is appropriate for:

- primary navigation;
- top toolbar;
- temporary status overlays;
- small floating controls where underlying content does not need to be read through the surface.

Translucency shall not be the default for:

- data grids;
- statistical result cards;
- chart canvases;
- profile tables;
- transformation previews;
- forms containing dense values.

Analytical content surfaces should be solid or near-solid.

---

# 4. HeroUI design system

HeroUI v3 is the source of theme colors, component variants, interaction states, and form and table styling. The frontend imports `@heroui/styles/css` and uses `@heroui/react` components for buttons, inputs, selects, checkboxes, cards, and analytical tables. Tailwind CSS v4 builds the library styles. `next-themes` applies HeroUI's light or dark theme according to the operating system.

The app's CSS defines the workspace layout and specialist analytical presentation. It is placed in the `app` cascade layer, after HeroUI's base styles and before HeroUI component styles, so the library retains ownership of control appearance. `globals.css` bridges older workspace variables such as `--text`, `--content`, and `--content-subtle` to HeroUI's `--foreground`, `--surface`, and `--surface-secondary`. Workspace modules should use these semantic colors and avoid fixed light or dark values.

HeroUI `primary` marks the main commit or advance action in each decision area. Supporting actions use `tertiary`; navigation uses `ghost`. The library supplies disabled, hover, focus, and pressed states. Custom CSS should add layout only where necessary. Data grids with viewport virtualization remain specialist views and use HeroUI theme tokens; bounded analytical tables use HeroUI Table.

Typography keeps the app's Inter font binding. The workspace spacing and panel radius aliases remain in `design-system.css`. Shadows separate surfaces gently, while dense tables and charts stay solid and legible.

---

# 5. Interaction principles

## 5.1 Preview before destructive/derived actions

Data transformations must use:

`configure → preview → inspect impact → apply`

The Apply action stays disabled until a valid preview exists for the current operation configuration.

Changing the operation or one of its parameters invalidates the existing preview.

## 5.2 Version visibility

When a dataset is loaded, the current version number shall appear in the global toolbar and in version-sensitive workspaces where useful.

Opening an older version changes the analytical source. Explore and Analyze must use that version immediately.

## 5.3 Read-only analytical stages

Explore and Analyze must not create the visual impression that a chart or test has changed the dataset. There is no Apply action in these stages.

## 5.4 Bounded loading

UI components shall communicate when data is intentionally bounded or truncated:

- preview pagination;
- frequency truncation;
- crosstab top-category bounds;
- chart sample limits;
- inference envelope errors.

The product must distinguish “showing a bounded visualization sample” from “running inferential statistics on a sample.” Inferential tests currently reject data beyond the interactive bound rather than silently sampling.

## 5.5 Control density

Only controls needed for the current analytical intent should be visible.

Examples:

- filter value input disappears for `is missing` / `is not missing`;
- Analyze only asks for variables that play a role in the selected analytical question;
- directional-hypothesis control appears only for tests that support direction;
- chart controls depend on variable type and chart family.

---

# 6. Data import experience

## 6.1 Empty state

The empty Data screen shall use an editorial import surface with:

- eyebrow context;
- large value proposition heading;
- concise explanation;
- drag/drop region;
- choose-file action;
- supported-format text;
- architecture assurances at the bottom (direct upload, immutable Parquet, reproducible versions).

The current primary heading is intentionally large because the page has very low information density before import.

## 6.2 File selection

Accepted file types in the current UI are CSV and Parquet.

After selection show:

- filename;
- file size;
- Replace action;
- editable dataset name;
- primary `Open data workspace` action.

Invalid extension selection shall produce an error and shall not start upload.

## 6.3 Upload and processing progress

The current progress model has three visible stages:

1. Upload
2. Ingest
3. Profile

Upload should use real byte progress where available. Ingestion status is polled through the backend. Profiling is shown as a separate final stage.

Status copy must be specific, for example:

- `Uploading directly to private storage`;
- `Waiting for ingestion worker`;
- `Canonicalizing dataset`;
- `Profiling data quality`.

Avoid generic `Loading…` when a more precise operation is known.

## 6.4 Error recovery

Import failure UI shall include:

- clear failure heading;
- useful error detail;
- retry action;
- preserved file/dataset selection when retry is safe.

---

# 7. Data workspace

## 7.1 Dataset overview

Once ready, the Data stage shall show:

- dataset name;
- canonical format;
- artifact size;
- version number;
- quality-health chip.

## 7.2 Summary metrics

The current four top-level metrics are:

1. rows;
2. columns;
3. missing cells (percentage + count);
4. duplicate rows (percentage + count).

Metrics use compact solid cards and should remain scannable without chart decoration.

## 7.3 Data grid

The preview grid shall:

- use a sticky column header;
- show row numbers separately from data columns;
- use approximately `38px` row height;
- use ellipsis for overflowing cells;
- expose full cell content via title/tooltip behavior where practical;
- style null values distinctly but legibly;
- use previous/next pagination;
- render a virtualized subset of the current page.

The current backend page maximum is 200 rows and the frontend uses 200-row pages.

The grid shall remain horizontally scrollable rather than compressing columns into unreadable widths.

## 7.4 Profile panel

The profile panel shall show:

- quality warnings before the column list;
- one compact column item per field;
- display name;
- logical type;
- missing percentage;
- distinct count.

Warnings shall show text plus status color. Warning meaning must not depend on color alone.

---

# 8. Prepare workspace

## 8.1 Desktop layout

Current desktop layout:

`220px tools/config | flexible preview canvas | 280px history`

Gap: `12px`.

Below `1180px`, history moves below the first two columns. Below `820px`, the workspace becomes one column.

## 8.2 Tool rail

Current tools:

- Fill missing
- Remove duplicates
- Filter rows
- Change type
- Rename column
- Drop column

Each tool item shall contain:

- short imperative label;
- one-line explanation;
- selected state;
- hover state.

## 8.3 Configuration panel

Configuration uses native/selectable form controls with a minimum control height around `38px`.

Column selection always uses the current version schema.

Validation errors must be presented before or during preview rather than silently coercing invalid values.

## 8.4 Preview canvas

Before a preview exists, show an explicit empty state rather than an empty table.

A valid transformation preview shall show:

- Before row count;
- After row count;
- Change in rows;
- output sample;
- output schema effects where represented by the tool;
- clear statement that the preview is read-only.

## 8.5 Apply action

Apply shall be visually primary relative to Preview only after a preview exists. Before that, Apply remains disabled.

On Apply:

- indicate work in progress;
- poll durable job status;
- on success switch to the new version;
- refresh profile/preview/history;
- clear stale preview/config state where appropriate.

## 8.6 History rail

The history rail shall expose:

- original imported version;
- each successful transformation in sequence;
- output version number;
- operation type;
- human-readable operation summary;
- `Open version` action.

History is not an undo stack that mutates lineage. Opening a prior version simply selects an earlier immutable snapshot.

---

# 9. Explore workspace

## 9.1 Layout

The current Explore workspace uses:

`260px variable rail | flexible analytical canvas`

The variable rail lists the current version's columns with type and compact metadata.

## 9.2 Variable rail

A variable row shall include:

- display name;
- data type;
- compact quality/cardinality context;
- active/selected state.

Selection shall drive contextual summary/actions without mutating data.

## 9.3 Explore modes

Current modes include:

- Summary
- Correlation
- Crosstab
- Visualize

Modes are presented as compact segmented tabs rather than separate top-level pages.

## 9.4 Summary mode

For the selected variable, present applicable descriptive metrics in a small grid/list. Metrics that are mathematically undefined for the variable type should not be presented as misleading zeros.

Frequency output should be tabular and indicate truncation when applicable.

## 9.5 Correlation mode

Correlation UI shall:

- operate only on compatible numeric variables;
- show variable names on both matrix axes;
- use a heatmap for visual scanning;
- preserve numeric values for exact inspection.

## 9.6 Crosstab mode

Crosstab UI shall:

- require two categorical-compatible variables;
- show counts and totals;
- make category truncation/bounds clear;
- avoid presenting omitted/null categories as zero-valued real categories.

When category limits exclude values, the displayed totals cover only the shown intersections; this must be stated beside the table. Changing either categorical variable clears the prior table until recalculation completes.

## 9.7 Visualization mode

Current supported chart families:

- histogram;
- bar;
- line;
- scatter;
- box;
- heatmap;
- normal Q-Q.

Chart selection shall be constrained by variable type and required roles.

Charts use Apache ECharts. Chart surfaces are solid/near-solid analytical canvases, not glass cards.

## 9.8 Chart behavior

Charts should:

- use responsive resizing;
- provide readable titles/axis labels;
- preserve tooltip inspection;
- avoid unnecessary 3D/decorative effects;
- keep chart chrome subordinate to the data;
- use bounded data payloads for performance;
- remain interpretable in both light and dark color schemes;
- derive font, text, muted, border, surface and accent colors from the live design-system tokens;
- set animation duration to zero when `prefers-reduced-motion: reduce` is active;
- update their rendered theme if the OS color-scheme preference changes while the chart is mounted.

---

# 10. Analyze workspace

## 10.1 Core UX principle

Analyze begins with the user's question, not with a list of statistical test names.

The opening prompt is effectively:

**“What are you trying to learn?”**

Current question families:

- Compare groups
- Compare paired values
- Measure a relationship
- Test categorical association
- Compare with a reference

## 10.2 Variable roles

After selecting a question, show only the required roles.

Examples:

- independent group comparison: numeric outcome + categorical group;
- paired comparison: numeric variable A + numeric variable B;
- numeric relationship: numeric X + numeric Y;
- categorical association: categorical A + categorical B;
- one-sample: numeric variable + reference value.

The UI must prevent obviously incompatible column types from being offered in a role selector.

## 10.3 Recommendation stage

The user explicitly requests recommendations after configuring roles.

Recommendation cards shall show:

- test name;
- Preferred badge when applicable;
- short rationale;
- relevant assumptions;
- selectable active state.

The UI may offer both parametric and nonparametric methods when both are valid, but should not imply that a nonparametric test is automatically “better” merely because it has fewer distributional assumptions.

## 10.4 Hypothesis direction

Directional controls appear only for tests whose API supports directional alternatives.

Current choices:

- Two-sided
- Less than / negative association
- Greater than / positive association

## 10.5 Result hierarchy

The result view shall prioritize statistical information in this order:

1. test name and null hypothesis;
2. estimate;
3. confidence interval/uncertainty;
4. statistic and degrees of freedom;
5. p-value and alpha context;
6. effect size and magnitude label when defined;
7. plain-language interpretation;
8. descriptive group context;
9. assumptions/diagnostics;
10. warnings;
11. linked visual evidence.

The visual hierarchy must not make the p-value the largest or only emphasized value.

## 10.6 Evidence badge

The result may show whether `p < α` or `p ≥ α`, but wording shall refer to statistical evidence rather than “proving” or “accepting” a hypothesis.

## 10.7 Diagnostic cards

Each diagnostic card shall show:

- diagnostic name;
- status (`pass`, `warning`, `info`, or `unavailable`);
- explanation;
- statistic/p-value where defined;
- sample size when relevant.

A warning diagnostic must not prevent the user from seeing the result unless the test itself is mathematically invalid. The diagnostic exists to qualify interpretation.

## 10.8 Large-data behavior

If the current inference request exceeds the interactive envelope, the UI shall show an explicit execution-limit message. It must not imply that the test ran on a hidden sample.

---

# 11. Model workspace — supervised MVP and planned extensions

The Model stage should reuse the product's progressive-disclosure pattern.

Recommended flow:

1. Choose modeling goal/problem type.
2. Assign target.
3. Select predictors.
4. Review detected data-preparation requirements.
5. Configure split/cross-validation.
6. Select baseline and candidate models.
7. Submit training.
8. Review comparison metrics.
9. Inspect best-model diagnostics/explainability.
10. Completed model evaluations are saved to Results automatically.

The current workspace supports regression and classification, target and predictor selection, a test split, seed, training-only validation (holdout or optional three-fold cross-validation), baseline and candidate comparison, confusion matrix for classification, and feature coefficients or importances for the selected best candidate. Runs and fitted pipelines are durable job artifacts. Unsupervised modeling remains planned.

The default interface should not expose every estimator hyperparameter. A compact basic configuration should exist first, with an advanced disclosure for expert settings.

The UI must clearly differentiate:

- training data;
- validation/cross-validation;
- untouched test evaluation;
- fitted preprocessing;
- baseline performance.

Model progress should use the same durable-job mental model already established by ingestion and transformations.

---

# 12. Results workspace

Results shall behave as a curated analytical record, not as a generic file browser.

Each saved result card should record:

- result type;
- title;
- exact dataset version;
- relevant variables/model;
- creation timestamp;
- primary metric/statistic;
- status/warnings;
- open/details action;
- include/exclude from report action.

The report composer should allow reordering selected result blocks without changing the underlying analysis resources.

---

# 13. Component behavior rules

## 13.1 Buttons

Use three conceptual levels:

- **Primary:** commits or advances the principal task (`Open data workspace`, `Apply`, `Run selected test`).
- **Secondary:** valid supporting action (`Choose file`, `Preview`, pagination).
- **Tertiary/ghost:** navigation, contextual actions, small utilities.

Use the HeroUI `primary` button variant for commit and advance actions. Avoid multiple visually primary actions within one decision area.

Every enabled interactive button style shall define a meaningful hover response, preserve the global keyboard focus indicator, and avoid motion larger than the small press/selection translations already used by the system.

## 13.2 Disabled controls

Disabled controls use reduced opacity and non-interactive cursor behavior. They must remain legible enough to communicate available product structure.

## 13.3 Form fields

- Labels appear above controls.
- Use HeroUI inputs, selects, and checkboxes for standard forms; keep the native file chooser for dataset imports.
- HeroUI supplies visible keyboard focus treatment.
- Validation copy should be close to the related controls when possible.
- Type-specific values must not be silently accepted when invalid.
- Hover may strengthen the control border without changing layout.

## 13.4 Badges/chips

Use chips for compact state/context such as:

- dataset version;
- health status;
- Preferred statistical test;
- evidence threshold state;
- variable type.

Badges should not be used for long explanatory text.

## 13.5 Tables

Tables should use:

- sticky headers when vertically scrollable;
- tabular numerals for metrics;
- subtle horizontal separators;
- text ellipsis only when full value remains inspectable;
- horizontal scrolling rather than shrinking below readable column width.

## 13.6 Empty states

Every analysis panel requiring configuration shall have an intentional empty state explaining the next action. Do not display a blank white region.

---

# 14. Motion

Motion must be functional and restrained.

Current behavior includes:

- `140ms` fast hover/control transitions;
- `160ms` selection transitions;
- `220ms` progress-width transitions;
- small busy/pulse indicators;
- ECharts animation around `260ms` when reduced motion is not requested;
- no page-scale decorative animation requirement.

When `prefers-reduced-motion: reduce` is active:

- global transitions and animations are effectively disabled;
- workspace spinner/pulse animations stop;
- chart animation duration becomes zero;
- no information may depend on animation.

---

# 15. Responsive behavior

## 15.1 Desktop (>1120/1180px depending workspace)

Use full analytical multi-column layouts.

## 15.2 Medium screens

- Data profile panel stacks below the data grid below approximately `1120px`.
- Prepare history moves below tools/canvas below approximately `1180px`.
- Explore/Analyze side rails may stack or collapse as their module breakpoints require.

## 15.3 Compact/tablet (≤820px)

Current shell behavior:

- app becomes one column;
- sidebar becomes horizontal navigation;
- secondary brand text/status/indexes are hidden;
- toolbar remains sticky with reduced top offset;
- metric grids reduce column count;
- dataset overview stacks vertically;
- Prepare becomes one column;
- multi-column impact/actions stack.

## 15.4 Mobile (≤560px)

- hide nonessential toolbar actions;
- reduce import padding;
- keep hero heading readable at approximately `38px`;
- stack error layouts;
- use one-column profile lists;
- preserve horizontal scrolling for dense data instead of compressing the grid.

Complex data analysis is desktop-first. Mobile support is for review, light configuration and continuity, not for forcing every dense visualization into a phone-sized layout.

---

# 16. Accessibility requirements

## 16.1 Keyboard

All primary workflows shall be operable using the keyboard. Native buttons, inputs and selects should remain native controls unless there is a strong reason otherwise.

## 16.2 Focus

Current global focus treatment:

- `2px` accent outline;
- `3px` outline offset.

No component may remove visible focus without supplying an equivalent or stronger replacement. Form controls that use an internal accent ring on `:focus` must still preserve a visible keyboard indication through the global `:focus-visible` treatment.

## 16.3 Semantics

Use:

- semantic buttons for actions;
- labels tied to form controls;
- headings in logical hierarchy;
- table semantics for true tabular output;
- meaningful ARIA labels for workspace regions and data grids where native semantics are insufficient.

## 16.4 Status messaging

Long-running progress and errors should be announced through appropriate live-region/status semantics when practical. Error copy must include text, not just a red border.

## 16.5 Color/contrast

Status colors must be accompanied by textual meaning. Status text shall use the dedicated semantic text roles rather than decorative status colors where normal-size copy is rendered. Both themes require WCAG 2.2 AA contrast for normal text, controls and chart labels.

## 16.6 Charts

Charts should be paired with textual/statistical values. A chart is never the sole representation of an inferential result.

---

# 17. Content and writing rules

Product copy should be concise, specific and statistically neutral.

Preferred:

- `Canonicalizing dataset`
- `No quality warnings`
- `Preview before apply`
- `Recommended methods`
- `p < α`
- `Evidence is consistent with a difference…`

Avoid:

- `Magic cleanup`
- `AI fixed your data`
- `The hypothesis is proven`
- `This result is definitely important`
- jargon without nearby explanation when a plain label exists.

The UI may use technical terminology when the terminology is the object the user must reason about, but contextual helper text should explain consequences.

---

# 18. Version-state rules

1. The selected dataset version is a first-class UI state.
2. Opening a previous version must refresh Data profile/preview and Prepare history context.
3. Explore always analyzes the selected version.
4. Analyze always analyzes the selected version.
5. Analyze state should remount/reset on `version_id` change so a result cannot visually survive a version switch.
6. Model runs and Results resources visibly record their source version.

---

# 19. Loading and failure-state matrix

| Area | Loading state | Failure state | Recovery |
| --- | --- | --- | --- |
| Upload | byte progress | upload error | retry/replace file |
| Ingestion | queued/running stage | persisted job failure | retry import/new analysis |
| Profile | profiling state | profile fetch error | retry/open version |
| Preview | grid loading indicator | preview error | retry page |
| Transform preview | working indicator | validation/execution error | change config/retry |
| Transform apply | durable-job busy state | persisted job error | retain source version; retry |
| Explore query | local progress state | 422/404/network error | revise variables/retry |
| Analyze recommendation | calculation state | validation error | revise roles/retry |
| Analyze run | calculation state | invalid test/limit/error | revise config or move to future deferred path |
| Model | durable training-job progress | training failure | inspect config/retry |
| Export | generation progress | export failure | retry without losing source result |

---

# 20. Design guardrails for future work

1. Do not introduce a second unrelated design language for Model or Results.
2. Do not use glass panels for dense result content merely because glass exists in the shell.
3. Do not hide dataset-version context on analytical screens.
4. Do not convert Prepare into an in-place spreadsheet editor; transformations remain reproducible operations.
5. Do not expose arbitrary statistical tests without the guided intent path as the default.
6. Do not make p-values the sole or dominant result visualization.
7. Do not silently sample inferential data for speed.
8. Do not add large permanent toolbars of rarely used controls; use contextual disclosure.
9. Do not force desktop-density tables into tiny responsive cards that destroy row/column relationships.
10. Keep visual emphasis proportional to analytical importance.
11. Do not introduce undeclared CSS custom properties for theme, status, surface, typography, radius or motion roles.
12. Do not hardcode alternate brand blues for primary actions; use the shared accent/action tokens.

---

# 21. Current implementation map

| UI area | Primary source files |
| --- | --- |
| Global shell/base tokens/Data | `src/app/globals.css`, `src/components/data-workspace.tsx` |
| Semantic design-system roles/font binding | `src/app/design-system.css`, `src/app/layout.tsx` |
| Prepare | `src/components/data-workspace.tsx`, `src/components/prepare-workspace.module.css` |
| Explore | `src/components/explore-workspace.tsx`, `src/components/explore-workspace.module.css` |
| Charts | `src/components/explore-chart.tsx` |
| Analyze | `src/components/analyze-workspace.tsx`, `src/components/analyze-workspace.module.css` |
| Model | `src/components/model-workspace.tsx`, `src/components/model-workspace.module.css` |
| Results | `src/components/results-workspace.tsx`, `src/components/results-workspace.module.css` |
| Typed API clients | `src/lib/dataset-upload.ts`, `src/lib/prepare-api.ts`, `src/lib/explore-api.ts`, `src/lib/analyze-api.ts`, `src/lib/model-api.ts`, `src/lib/results-api.ts` |

---

# 22. Related documentation

- [`SRS.md`](SRS.md) — functional and non-functional requirements.
- [`architecture.md`](architecture.md) — runtime, data, persistence and deployment architecture.
- [`serverless-architecture.md`](serverless-architecture.md) — dated Vercel runtime research.
