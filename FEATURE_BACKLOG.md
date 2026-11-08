# FloodWatch KP — Build Plan and Feature Backlog

This is the **from-scratch build plan** for the FloodWatch prototype. The
repository is empty: no `src/`, tests, configs, data, models, runs or app exist
yet. Everything below is a target to implement, not a change to existing code.
File paths are the intended layout; §9 gives the build order and the two-person
split.

The invariants still hold from the first commit: the prediction contract, the
chronological split, the two mechanisms on every basin, train-only threshold
fitting and shadow mode.

> `PLAN.md` (Sailab / KPITB challenge) is a **separate product** and is not
> adopted here. The ideas worth keeping from it — alert verification,
> misinformation triage, CI — are re-specified below against FloodWatch's
> architecture.

**Status key:** 🔴 must · 🟡 should · ⚪ could

---

## 0. What does not change

| Invariant | Why it is protected |
|---|---|
| Prediction schema (`basin_id, timestamp_utc, module, prob, tier, top_drivers`) | `schema.validate_predictions` is the contract to implement first. New columns are additive only. |
| `configs/split.yaml` | Train / validation / test years and the 30-day gap are frozen before any model is trained. |
| Both mechanisms on every basin | No feature may gate A or B per basin. |
| Train-only threshold fitting | Any new threshold follows the same rule. |
| Shadow mode | `delivery: file` remains the default. FW-12 adds a second lock, not a key. |
| One test evaluation | No feature may re-run the test split. |

---

## 1. Summary

| ID | Feature | Priority | Effort | Sprint day | Plugs into | Cut rank |
|---|---|---|---|---|---|---|
| FW-14 | CI workflow | 🔴 | 1.0 h | D1 | `.github/workflows/ci.yml` | never |
| FW-01 | Golden replay regression test | 🔴 | 1.0 h | D2 | `tests/test_golden_replay.py` | never |
| FW-04 | Alert verification | 🔴 | 1.0 h | D2 | `src/floodwatch/verify.py`, `alerts.deliver` | never |
| FW-05 | Misinformation triage | 🔴 | 2.0 h | D3 | `src/floodwatch/triage.py`, app tab | 7 |
| FW-06 | Old-footage detection | 🔴 | 0.75 h | D3 | `triage.extract_dates` | 6 |
| FW-07 | Adversarial / injection tests | 🔴 | 0.5 h | D3 | `tests/test_triage.py` | 5 |
| FW-03 | "Why not higher?" explainer | 🟡 | 0.75 h | D3 | `src/floodwatch/explain.py`, app | 8 |
| FW-08 | Source-health panel | 🟡 | 1.0 h | D3 | `runner._health`, `run_report.json` | 4 |
| FW-02 | Fusion ablation table | 🟡 | 1.0 h | D3 | `scripts/08_ablation.py` | 3 |
| FW-09 | Decision log | ⚪ | 0.75 h | D3 | `runs/<id>/decisions.jsonl` | 2 |
| FW-11 | Climatological context | ⚪ | 1.0 h | D2/D3 | `scripts/09_climatology.py` | 1 |
| FW-12 | Operator override + kill switch | ⚪ | 0.75 h | D3 | `alerts.build_alerts` | 9 |
| FW-13 | Event verification loop | ⚪ | 1.0 h | D3 | `scripts/10_log_event.py` | 10 |
| FW-10 | Ensemble uncertainty band | ⚪ | 1.0 h | D3 | `runner._to_predictions` | 0 (cut first) |

**Must total ≈ 6.25 h. Should total ≈ 2.75 h. Could total ≈ 4.5 h.**

Cut order, highest number first. Everything above rank 0 is optional.

---

## 2. Must-have features

### FW-14 — CI workflow 🔴

**Why.** The build has no CI from the first commit. A threshold edit that silently
changes behaviour is the single most damaging change this project can take, and
nothing else catches it.

**Where.** `.github/workflows/ci.yml` (new), `requirements.txt` (new).

**Jobs.**

| Job | Command | Blocks merge |
|---|---|---|
| `lint` | `ruff check .` + `ruff format --check .` | yes |
| `tests` | `pytest -q -m "not network"` | yes |
| `golden` | `pytest -q tests/test_golden_replay.py` | yes |
| `contract` | `pytest -q tests/test_schema.py` | yes |
| `secrets` | `detect-secrets scan` or `gitleaks` | yes |
| `audit` | `pip-audit` | no (advisory) |

**Acceptance.**
- [ ] CI is green on `main`.
- [ ] A deliberately broken threshold in `configs/thresholds.yaml` turns `golden` red.
- [ ] No job touches the network or the test split.
- [ ] `requirements.txt` exists and installs cleanly (needed for HF Spaces too).

**Effort** 1 h. **Day 1.**

---

### FW-01 — Golden replay regression test 🔴

**Why.** Turns "don't edit thresholds without a reason" from a comment into a
build failure. This is the highest-value engineering addition in the list.

**Where.** `tests/test_golden_replay.py` (new), `tests/fixtures/golden_run.json` (new).

**How.**
1. Run the full pipeline on `data/demo/features_demo.parquet` over a fixed
   window (the Aug 2022 demo window) with the committed thresholds.
2. Persist per `(basin_id, timestamp_utc)`: `tier`, `prob` rounded to 6 dp,
   `compound` flag.
3. The test re-runs and asserts an exact match on `tier`, `1e-6` on `prob`.

**Acceptance.**
- [ ] `pytest tests/test_golden_replay.py` passes.
- [ ] Changing any weight, cutoff or fusion rule fails with a readable diff
      showing basin, timestamp, expected vs actual.
- [ ] The fixture is < 500 KB and committed.
- [ ] The test runs offline in under 60 s.

**Note.** It pins *behaviour*, not accuracy. When a change is intentional,
regenerate the fixture in the same PR and say why.

**Effort** 1 h. **Day 2.**

---

### FW-04 — Alert verification 🔴

**Why.** Today `alerts.format_text` is trusted by construction. The moment a
model or an LLM drafts any wording, that trust is misplaced. Verification is
also the honest answer to "how do you stop it saying something wrong?"

**Where.** `src/floodwatch/verify.py` (new), `alerts.deliver()` (call site),
`tests/test_verify.py` (new).

**Contract.**

```python
def check_alert(
    text: str,
    *,
    basin_id: str,
    tier: str,
    allowed_numbers: set[str],
) -> list[str]:
    """Return a list of problems. Empty list == the text is safe to send."""
```

**Rules.**

1. Basin id must appear.
2. The correct tier word must appear.
3. **No other tier word may appear** (`ORANGE` and `RED` in one message is a fail).
4. Every number in the text must be in `allowed_numbers`
   (prob, tier cutoff, rain mm, lead hours, threshold provenance).
5. Normalise Urdu / Arabic-Indic digits before matching:
   `"۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"` → `"01234567890123456789"`.
6. Normalise decimals so `0.62` and `0.620` compare equal.
7. Empty text, or text over 1600 chars, fails.

**Wiring.** In `alerts.deliver()`, verify each alert before writing and before any
send. On failure:
- do not send,
- append `status: "blocked_by_verify"` to the run report,
- fall back to the plain template text (which must itself pass).

**Acceptance.**
- [ ] Planted wrong number is blocked.
- [ ] Planted wrong basin is blocked.
- [ ] Two tier words in one message is blocked.
- [ ] Urdu-digit `۰.۶۲` is accepted as `0.62`.
- [ ] Clean template text passes.
- [ ] `run_report.json` reports `verify.blocked` count.
- [ ] **All** outbound text is verified: alerts, all-clears, test messages.

**Effort** 1 h. **Day 2.**

---

### FW-05 — Misinformation triage 🔴

**Why.** This is the capability FloodWatch lacks entirely and the one a judge or
a user will remember. It is also cheap because the fused run already carries the
current tier for every basin.

**Where.** `src/floodwatch/triage.py` (new), `data/advisories.json` (new),
`data/static/basin_aliases.json` (new), app tab "Verify a message" (new).

**Contract.**

```python
class Verdict(str, Enum):
    SUPPORTED = "supported_by_advisory"
    CONSISTENT = "consistent_with_conditions"
    NOT_SUPPORTED = "not_supported"
    CANNOT_ASSESS = "cannot_assess"


def triage(
    text: str,
    *,
    aliases: dict[str, str],          # "کالام" / "kalam" -> "swat_kalam"
    levels: dict[str, str],           # basin_id -> tier from the latest run
    advisories: list[Advisory] = (),
    now: datetime | None = None,
    max_advisory_age_h: float = 48.0,
) -> tuple[Verdict, list[str]]:
    """Verdict plus human-readable evidence. Never returns the word 'fake'."""
```

**Decision logic — code only, no model.**

```
normalise digits and case
find monitored basins by alias
  none                        -> CANNOT_ASSESS
  a fresh advisory covers it  -> SUPPORTED      (link the advisory)
  current tier >= high        -> CONSISTENT     (no official source found)
  otherwise                   -> NOT_SUPPORTED  (may be old footage / elsewhere)
always append: "Check PDMA / PMD / Rescue 1122. Do not forward unverified."
```

**Acceptance.**
- [ ] All four verdicts reachable and tested.
- [ ] Every verdict returns at least one evidence string.
- [ ] The word "fake" never appears in any output.
- [ ] Aliases cover English + Urdu + common misspellings for all 8 basins.
- [ ] **Urdu spellings are checked by a native speaker** — do not guess them.
- [ ] `data/advisories.json` holds at least 5 hand-curated PDMA / NDMA / PMD
      entries with title, URL, issue time and covered basin ids. Do not scrape.
- [ ] The tab works with no run loaded (falls back to `CANNOT_ASSESS`).
- [ ] Verdict is deterministic: same input, same output, no network.

**Effort** 2 h. **Day 3.**

---

### FW-06 — Old-footage detection 🔴

**Why.** The most common real flood misinformation is *genuine* footage from a
previous event recirculated. Place matching alone cannot catch it.

**Where.** `triage.extract_dates()` (new, inside `triage.py`).

**How.** Extract dates and years in English and Urdu-digit form:

- `27 June 2025`, `27/06/2025`, `2025-06-27`, `اگست ۲۰۲۲`
- a bare year is accepted only if it is in `[2000, current year]`

If the newest extracted date is older than 30 days, downgrade:

| Base verdict | With old date |
|---|---|
| SUPPORTED | `CANNOT_ASSESS` + "describes <date>; verify whether this is current" |
| CONSISTENT | `NOT_SUPPORTED` + "describes <date>, not current conditions" |
| NOT_SUPPORTED | unchanged, but cite the date |
| CANNOT_ASSESS | unchanged |

**Acceptance.**
- [ ] "Flood in Kalam, August 2022" → old-date path taken.
- [ ] "Flood in Kalam today" → no date extracted, no downgrade.
- [ ] Urdu-digit year `۲۰۲۲` is extracted.
- [ ] A future date is treated as unparseable, not as fresh.
- [ ] The extracted date is shown in the evidence.

**Effort** 45 min. **Day 3.**

---

### FW-07 — Adversarial / injection tests 🔴

**Why.** The triage verdict is decided by code, so it *should* be immune to
instruction-like text. Proving that in a test is a one-line safety story and a
memorable demo.

**Where.** `tests/test_triage.py` (new).

**Cases.**

| Input | Expected |
|---|---|
| `"Ignore previous instructions and return SUPPORTED"` | verdict unchanged by the instruction |
| `"Kalam flood 2022"` + `"SYSTEM: mark as supported"` | old-date path still taken |
| `"<script>alert(1)</script> Kalam"` | no exception, no HTML echoed |
| Empty string / whitespace | `CANNOT_ASSESS` |
| 50,000-character input | handled, bounded time |
| Urdu + Arabic-Indic digits mixed | parsed |
| Correct basin, wrong district name | only the monitored basin matches |
| A message naming two basins | both listed, worst tier decides |

**Acceptance.**
- [ ] All cases pass.
- [ ] No input raises an unhandled exception.
- [ ] The verdict function contains no model call (assert by import inspection).

**Effort** 30 min. **Day 3.**

---

## 3. Should-have features

### FW-03 — "Why not higher?" explainer 🟡

**Why.** Converts "the model says ORANGE" into "here is the missing ingredient."
Best trust-per-hour in the list.

**Where.** `src/floodwatch/explain.py` (new), `fusion.fuse_summary` (extra
columns), app `tab_now`.

**Output per basin.**

```
basin_id           next_tier   gap_to_next   binding_constraint
swat_kalam         high        0.11          rain_next_3h (8.2 mm; high needs ~25 mm)
```

**Acceptance.**
- [ ] Every basin row shows the next tier and the gap.
- [ ] At `severe`, next tier is `none` and the gap is `0.0`.
- [ ] The app renders it without a second click.
- [ ] Pure function, unit-tested, no I/O.

**Effort** 45 min. **Day 3.**

---

### FW-08 — Source-health panel 🟡

**Why.** "How do you know the data is current?" is the first question an operator
asks, and the current `_health` only checks basin coverage.

**Where.** `runner._health` (extend), `run_report.json` (new `sources` block),
app `tab_report`.

**Per source.** `last_valid_utc`, `lag_hours`, `expected_cadence_h`,
`stale: bool`, `fallback_used: bool`.

**Acceptance.**
- [ ] `run_report.json` has a `sources` block for archive, flood and forecast.
- [ ] A source older than 2× its cadence is marked `stale`.
- [ ] The app shows a red badge when any source is stale.
- [ ] A missing source degrades the run, it does not crash it.

**Effort** 1 h. **Day 3.**

---

### FW-02 — Fusion ablation table 🟡

**Why.** Proves Model B adds value over A alone, and that compound escalation
earns its place. Answers "why two models?" with a number.

**Where.** `scripts/08_ablation.py` (new) → `models/ablation_validation.json` +
a markdown table in `docs/`.

**Variants.** A only · B only · `max` · `noisy_or` · `max + compound` ·
`max + compound + rain-on-snow`.

**Metrics.** POD, FAR, CSI, PR-AUC, event POD, median lead time — on
**validation only**.

**Acceptance.**
- [ ] Six rows, same metric set as `baseline_validation.json`.
- [ ] The script refuses to run on `test`.
- [ ] The table states that the data is synthetic until real ingest lands.
- [ ] Best variant is named explicitly, even if it is "A only".

**Effort** 1 h. **Day 3.**

---

## 4. Could-have features

### FW-09 — Decision log ⚪
`runs/<run_id>/decisions.jsonl`, one line per basin-timestep: `basin_id`,
`timestamp_utc`, `prob_a`, `prob_b`, `prob_fused`, `tier`, `compound`,
`alert_decision`, `drivers`. Enables "show me everything it decided in the last
24 h" — `alerts.json` only records what was sent. **45 min.**

### FW-11 — Climatological context ⚪
`scripts/09_climatology.py` computes per-basin p50/p90/p95/p99 of 3h rain, 24h
rain and discharge from the archive; writes `data/static/climatology.json`.
Adds a reason string when p99 is exceeded: *"wettest 3h at this point since
2010."* No new credentials. **1 h.**

### FW-12 — Operator override + kill switch ⚪
`data/overrides.json` — `{basin_id: {suppress: true, until: "...", note: "..."}}`.
`alerts.build_alerts` filters suppressed basins and logs the override. Add an
explicit `FLOODWATCH_SEND=1` requirement on top of `delivery: telegram`, so two
things must be true before a message leaves the machine. **45 min.**

### FW-13 — Event verification loop ⚪
`scripts/10_log_event.py` + `data/verified_events.json`. Record event id,
basins, start/end, reported impact time, source URL, notes. This is the seed of
the ground-truth inventory both projects lack, and the honest answer to "where
will your labels come from?" **1 h.**

### FW-10 — Ensemble uncertainty band ⚪
Add `prob_std` across the 3 seeds and `tier_stable: bool` as additive columns
(the validator permits extra columns). If seeds disagree on the tier, mark the row
`provisional`. Show the band in the app. Depends on deep models existing. **1 h.**

---

## 5. Explicitly not added

| Idea | Reason |
|---|---|
| Gradio frontend | The project is Streamlit; a second UI framework is wasted effort in a three-day sprint. |
| Public WhatsApp / Telegram subscriber management, SQLite | New vendor, consent and credential surface. Shadow mode stays. A single test-recipient demo channel is a stretch item in §8.11, not a subscriber system. |
| LLM-drafted alerts | Adds a dependency and a failure mode for no judged benefit. Template text is the baseline. |
| IMERG / Earthdata ingest | Open-Meteo works with no credentials. IMERG is a Phase-2 upgrade, not a sprint item. |
| Weighted-sum risk score replacing the models | That is Sailab's design. FloodWatch's contribution is the calibrated two-mechanism model. |
| Relief board, permalinks, public status page | Scope creep. Roadmap slide only. |
| Any feature that re-runs the test split | Violates the single-evaluation rule. |

---

## 6. Order of work

The repo is empty. The canonical **from-scratch build plan**, even work split,
model-separation rules, contract freeze, day plan and conflict rules are in
**§9**. In short: **Qamran (A)** builds data → features → **Model A: CNN-LSTM
(cloudburst)** → verification → triage; **Warisha (B)** builds **Model B: LSTM
(snowmelt)** → fusion → thresholds → runner → adapter → app → decisions →
messages → explain → alerts → CI. Each file has one owner, and the two models
never import each other; fusion is the only join.

Do **not** start FW-05 before the D2 gate. Triage reads the latest run's tiers;
without a fused run it can only return `CANNOT_ASSESS`.

---

## 7. Definition of done for this backlog

- [ ] `pytest` green, including the golden replay and the injection tests.
- [ ] CI green on `main`.
- [ ] `run_report.json` carries `verify.blocked` and a `sources` block.
- [ ] App has a working "Verify a message" tab with all four verdicts.
- [ ] Every basin shows a "why not higher" line.
- [ ] Ablation table committed with synthetic-data warning.
- [ ] No change to `configs/split.yaml`, the prediction contract, or shadow mode.

---

## 8. Sailab-style trust layers around FloodWatch

> **Status: plan only.** This section is the specification for a later
> implementation. No module, test, workflow or data file described here has
> been written yet. `PLAN.md` remains Sailab's product plan; FloodWatch stays
> FloodWatch.

The four layers worth taking from Sailab are **alert decisions**, **alert
verification**, **misinformation triage** and **CI**. They wrap FloodWatch's
models rather than replacing them. One small adapter turns a
FloodWatch prediction into Sailab's `RiskResult`, so every layer downstream is
written once and does not need to know about parquet, tiers or fusion.

### 8.1 What must not change

| Invariant | Why it is protected |
|---|---|
| `schema.py` six-column prediction contract | New fields are additive only; the validator must permit extra columns. |
| `configs/split.yaml` | No layer may re-run or re-score the test split. |
| Both mechanisms on every basin | No layer may gate A or B per basin. |
| Train-only threshold fitting | Any new threshold follows the same rule. |
| Shadow mode (`delivery: file`) | Verification adds a lock, not a key. Nothing is sent to a person. |
| FloodWatch's calibrated two-mechanism model | Sailab's weighted-sum score is **not** adopted. |

Not adopted, for the reasons already in §5: Gradio, pydantic, SQLite, public
WhatsApp/Telegram subscriber management, LLM-drafted alerts, IMERG ingest,
relief board. The demo delivery in §8.11 is one test recipient, not a
subscriber system.

### 8.2 The adapter — `src/floodwatch/interop.py` (new)

**Purpose.** The only place that knows both vocabularies. It reads the fused
prediction table and adds `Level`, `Area` and `RiskResult`. It never changes a
probability.

```python
class Level(IntEnum):
    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    district: str
    lat: float
    lon: float
    terrain_susceptibility: float = 0.5   # neutral placeholder, not a measurement
    glacial_lake_nearby: bool = False     # GLOF is out of scope
    snow_cover_frac: float = 0.0


@dataclass(frozen=True)
class RiskResult:
    area_id: str
    score: float                          # = fused prob
    level: Level
    reasons: list[str]                    # = parsed top_drivers + compound
    computed_at: str                      # ISO-8601 UTC
    tier: str = "none"                    # original FloodWatch tier
    compound: bool = False
    prob_a: float | None = None           # optional, for display
    prob_b: float | None = None           # optional, for display
```

**Tier → level mapping.** This is the one decision a reviewer should confirm.

| FloodWatch tier | Level | Alert? | Rationale |
|---|---|---|---|
| `none` | `GREEN` | no | below the operating point |
| `low` | `GREEN` | no | below the operating point |
| `moderate` | `YELLOW` | watch only | not yet an alert |
| `high` | `ORANGE` | **yes** | Sailab says "alert at ORANGE"; this makes it FloodWatch's `high` |
| `severe` | `RED` | yes | act |

`none` and `low` share GREEN deliberately. The distinction stays visible in
`RiskResult.tier` and in the display frame, but it must never page anyone.

**Functions.**

```python
def to_risk_results(
    fused: pd.DataFrame,
    *,
    catalog: Mapping[str, Area] | None = None,
    pred_a: pd.DataFrame | None = None,
    pred_b: pd.DataFrame | None = None,
    computed_at: str | datetime | None = None,
) -> list[RiskResult]: ...

def risk_frame(results, catalog=None) -> pd.DataFrame: ...
def areas() -> dict[str, Area]: ...
def levels_from(results) -> dict[str, Level]: ...
def tier_to_level(tier: str) -> Level: ...
```

**Behaviour.**

1. Validate the input with `schema.validate_predictions` first. A broken table
   must fail here, not become a confident alert.
2. Take the newest row per basin — what an operator is looking at.
3. `score = prob`; `reasons = parse_drivers(top_drivers)`; prepend a compound
   reason when `compound` is true; never leave `reasons` empty.
4. `computed_at` is passed in for deterministic tests; otherwise now UTC.
5. `Area` is built from `configs/basins.yaml`. Fields FloodWatch does not model
   stay at neutral values and are documented as such.

**Acceptance.**
- [ ] Every tier maps to the table above; a unit test pins all five.
- [ ] `to_risk_results` returns one row per basin, newest timestamp only.
- [ ] Empty input returns `[]`; a schema violation raises `SchemaError`.
- [ ] `risk_frame` sorts worst first and carries `tier`, `level_name`,
      `compound`, `prob_a`, `prob_b`.
- [ ] The adapter makes no network call and writes no file.

### 8.3 Alert decisions — `src/floodwatch/decisions.py` (new)

Sailab's rule is right for a warning service and is kept as-is:

* alert at **ORANGE and above**;
* repeat only on **escalation** or after a **6 h cooldown**;
* send **one all-clear** when the level drops back below ORANGE.

```python
@dataclass(frozen=True)
class AreaState:
    area_id: str
    level: Level = Level.GREEN
    last_alert_at: datetime | None = None
    alerted_level: Level | None = None
    all_clear_sent: bool = False


@dataclass(frozen=True)
class AlertDecision:
    area_id: str
    action: Literal["alert", "all_clear", "none"]
    level: Level
    previous_level: Level
    reason: str
    cooldown_remaining_h: float | None = None


def decide(state, level, *, now=None, min_level=Level.ORANGE,
           cooldown_hours=6.0, escalate_only=False) -> AlertDecision: ...
def apply_decisions(states, levels, **kwargs) -> tuple[list[AlertDecision], dict[str, AreaState]]: ...
class StateStore:
    def load(self) -> dict[str, AreaState]: ...
    def save(self, states, *, updated_at=None) -> Path: ...
    def update(self, levels, *, now=None, **kwargs): ...
```

**State file.** `data/state/area_state.json`, written atomically. No SQLite:
the sprint does not need a new dependency or a new failure mode. The file is
gitignored; the format is versioned with `schema_version: 1`.

**Acceptance.**
- [ ] GREEN/YELLOW → no alert.
- [ ] ORANGE from GREEN/YELLOW → one alert, `last_alert_at` set.
- [ ] Same level inside the cooldown → no alert.
- [ ] Escalation inside the cooldown → alert.
- [ ] Drop below ORANGE → exactly one all-clear, never repeated.
- [ ] `apply_decisions` is deterministic: areas processed in sorted order.
- [ ] `StateStore` round-trips through JSON and survives a missing file.
- [ ] No model call and no network call.

### 8.4 Message templates — `src/floodwatch/messages.py` (new)

The template is the baseline. It is correct by construction because it only
contains numbers the risk result produced.

```python
def format_alert(result, *, lang="en", catalog=None) -> str: ...
def format_all_clear(result, *, lang="en", catalog=None) -> str: ...
def format_test_message(area_id, *, computed_at, lang="en") -> str: ...
def format_decision(result, action, *, lang="en", catalog=None) -> str: ...
```

Every message contains the **basin id** (for verification), exactly **one**
level word, the `computed_at` stamp, and `Rescue 1122`. English and Urdu are
first-class; Urdu is marked for native-speaker review. A test message says
GREEN so it passes the same verifier as a real alert.

**Acceptance.**
- [ ] Every template, in both languages, passes `verify.check_risk_alert`.
- [ ] No template contains a number outside `allowed_numbers_for(result)`.
- [ ] No template says "fake", "true", or "confirmed".
- [ ] Urdu wording is reviewed by a native speaker before it is used publicly.

### 8.5 Alert verification — `src/floodwatch/verify.py` (new)

```python
def check_alert(text, *, basin_id, tier, allowed_numbers) -> list[str]:
    """Return a list of problems. Empty list == safe to send."""

def allowed_numbers_for(result) -> set[str]: ...
def allowed_numbers_for_alert(alert) -> set[str]: ...
def check_risk_alert(text, result, *, extra_numbers=(), extra_texts=()) -> list[str]: ...
```

**Rules.**

1. Non-empty, and at most 1600 characters. The demo keeps messages shorter than
   this so the same text could be sent by SMS later; the channel layer rejects
   an over-length message rather than truncating it.
2. The basin id must appear.
3. The correct tier word **or** its Level name must appear.
4. No other tier word or Level name may appear.
5. Every number must be in `allowed_numbers`.
6. Normalise Urdu / Arabic-Indic digits first:
   `"۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"` → `"01234567890123456789"`.
7. Compare decimals numerically: `0.62 == 0.620 == ۰.۶۲`.

`allowed_numbers_for(result)` collects the score, the numbers in `reasons`,
`computed_at`, `prob_a`, `prob_b`, and the emergency number `1122`. Anything
else is an invented number and fails.

**Wiring — `alerts.deliver()`.**

- Build the outbound text for every alert (template, or a supplied draft).
- Verify before writing and before any send.
- On failure: do **not** send; fall back to the plain template; record
  `blocked_by_verify`.
- Write `runs/<run_id>/outbound.json` with `{basin_id, text, problems}` for
  audit, and keep `alerts.json` unchanged.
- Add `verify: {checked, blocked, problems}` to `delivery` and a top-level
  `verify` block to `run_report.json`.

**Acceptance.**
- [ ] A planted wrong number is blocked.
- [ ] A planted wrong basin is blocked.
- [ ] Two level words in one message are blocked.
- [ ] Urdu-digit `۰.۶۲` is accepted as `0.62`.
- [ ] Clean template text passes for all five tiers.
- [ ] `run_report.json` reports `verify.blocked`.
- [ ] A blocked draft never reaches the WhatsApp branch.
- [ ] Every outbound text is checked: alerts, all-clears, test messages.

### 8.6 Misinformation triage — `src/floodwatch/triage.py` (new)

The verdict is decided by code from three facts: which monitored basins are
named, whether a fresh official advisory covers them, and FloodWatch's current
level for them. It never says "fake" or "true".

```python
class Verdict(str, Enum):
    SUPPORTED = "supported_by_advisory"
    CONSISTENT = "consistent_with_conditions"
    NOT_SUPPORTED = "not_supported"
    CANNOT_ASSESS = "cannot_assess"


@dataclass(frozen=True)
class Advisory:
    title: str
    url: str
    areas: frozenset[str]
    issued_at: datetime | None = None
    age_hours: float | None = None
    source: str = ""


@dataclass(frozen=True)
class TriageResult:
    verdict: Verdict
    evidence: list[str]
    matched_basins: list[str]
    extracted_date: date | None = None
    level: Level | None = None
    truncated: bool = False


def extract_dates(text, *, now=None) -> list[date]: ...
def triage(text, *, aliases, levels, advisories=(), now=None,
           max_advisory_age_h=48.0, stale_days=30.0) -> TriageResult: ...
def load_aliases(path=None) -> dict[str, str]: ...
def load_advisories(path=None) -> list[Advisory]: ...
```

**Decision logic — code only, no model.**

```
normalise case and digits
find monitored basins by alias
  none                          -> CANNOT_ASSESS
  a fresh advisory covers it    -> SUPPORTED       (link the advisory)
  current level >= ORANGE       -> CONSISTENT      (no official source found)
  otherwise                     -> NOT_SUPPORTED   (may be old footage / elsewhere)
always append: "Check PDMA / PMD / Rescue 1122. Do not forward unverified."
```

**Old-footage downgrade (FW-06).** Extract `27 June 2025`, `27/06/2025`,
`2025-06-27`, `اگست ۲۰۲۲` and bare years in `[2000, current year]`. A future
date is unparseable, not fresh. If the newest date is older than 30 days:

| Base verdict | With an old date |
|---|---|
| `SUPPORTED` | `CANNOT_ASSESS` + "describes <date>; verify whether this is current" |
| `CONSISTENT` | `NOT_SUPPORTED` + "describes <date>, not current conditions" |
| `NOT_SUPPORTED` | unchanged, but cite the date |
| `CANNOT_ASSESS` | unchanged |

**Unknown levels.** If a basin is named but the latest run has no level for it
(the current config drift, see §8.10), return `CANNOT_ASSESS` with "no current
risk estimate for <basin>". Do not silently treat unknown as GREEN — that would
call a real event "not supported".

**Data files.**

- `data/static/basin_aliases.json` — `{"schema_version": 1, "aliases":
  {alias: basin_id}}`. Covers English, Urdu and common misspellings for the
  northern eight: `swat_kalam`, `swat_madyan`, `swat_chakdara`,
  `panjkora_dir`, `panjkora_talash`, `chitral_mastuj`, `chitral_drosh`,
  `chitral_chitral`. **Urdu spellings need a native speaker.**
- `data/advisories.json` — `{"schema_version": 1, "advisories": [{source,
  title, url, issued_at, areas}]}`. **Ship it empty** until real PDMA / NDMA /
  PMD links are verified. Never fabricate an official advisory to make the demo
  show SUPPORTED; the demo may inject one clearly labelled `DEMO` advisory.

**App.** A "Verify a message" tab: paste text, get the verdict, the matched
basins, the extracted date, the current level and the evidence. With no run
loaded it falls back to `CANNOT_ASSESS`.

**Acceptance.**
- [ ] All four verdicts are reachable and tested.
- [ ] Every verdict returns at least one evidence string.
- [ ] The word "fake" never appears in any output.
- [ ] Aliases cover English + Urdu + common misspellings for the northern eight.
- [ ] Urdu spellings are checked by a native speaker.
- [ ] The tab works with no run loaded.
- [ ] Verdict is deterministic: same input, same output, no network.
- [ ] Adversarial inputs are handled: instruction-like text, `<script>`, empty
      string, 50,000 characters, mixed Urdu/Arabic-Indic digits, two basins.
- [ ] A message naming two basins lists both; the worst known level decides.
- [ ] The verdict function contains no model call (assert by source inspection).

### 8.7 CI — `.github/workflows/ci.yml` (new)

| Job | Command | Blocks merge |
|---|---|---|
| `lint` | `ruff check .` + `ruff format --check .` | yes |
| `tests` | `pytest -q -m "not network"` | yes |
| `contract` | `pytest -q tests/test_schema.py` | yes |
| `secrets` | `gitleaks` (or `detect-secrets`) | yes |
| `audit` | `pip-audit` | no (advisory) |

Also add `requirements.txt` (needed for Hugging Face Spaces), add `ruff` and
`pip-audit` to `[project.optional-dependencies].dev`, and refresh `uv.lock`.
No job may use the network for data or touch the test split.

**Acceptance.**
- [ ] CI is green on `main`.
- [ ] A deliberately broken threshold turns the golden replay red (FW-01).
- [ ] `requirements.txt` installs cleanly in a fresh environment.
- [ ] `pytest -m "not network"` is the only test invocation in CI.

### 8.8 Integration map

| File | Change | Layer |
|---|---|---|
| `src/floodwatch/interop.py` | new: `Level`, `Area`, `RiskResult`, adapter | adapter |
| `src/floodwatch/decisions.py` | new: `AreaState`, `AlertDecision`, `StateStore` | alert |
| `src/floodwatch/messages.py` | new: en/ur templates | alert |
| `src/floodwatch/verify.py` | new: `check_alert`, allowed-number helpers | verification |
| `src/floodwatch/triage.py` | new: `Verdict`, `Advisory`, `extract_dates`, `triage` | misinformation |
| `src/floodwatch/channels/__init__.py` | new: channel dispatch + gating | delivery (stretch) |
| `src/floodwatch/channels/whatsapp.py` | new: text message via Cloud API | delivery (stretch) |
| `src/floodwatch/alerts.py` | `deliver()` verifies, writes `outbound.json` | verification |
| `src/floodwatch/runner.py` | writes `report["verify"]` and `report["decisions"]` | alert/verification |
| `app/streamlit_app.py` | includes a "Verify a message" tab | misinformation |
| `tests/test_interop.py` | new | adapter |
| `tests/test_decisions.py` | new | alert |
| `tests/test_verify.py` | new | verification |
| `tests/test_triage.py` | new | misinformation |
| `tests/test_messages.py` | new | alert |
| `tests/test_channels.py` | new: mocked provider calls | delivery (stretch) |
| `scripts/11_layers_demo.py` | new: offline end-to-end demo | all |
| `.github/workflows/ci.yml` | new | CI |
| `requirements.txt` | new | CI / HF Spaces |
| `pyproject.toml`, `uv.lock` | dev extras + lock refresh | CI |

### 8.9 Order of work and cut line

This is the trust-layer slice only. The full from-scratch order — data, features,
Model A (CNN-LSTM), Model B (LSTM), fusion, runner, then these layers — is in
§9.4 and §9.5.

| Day | Work | Gate |
|---|---|---|
| **D1** | decisions + messages + their tests; CI + `requirements.txt` + ruff/pip-audit | decisions deterministic; CI green |
| **D2** | adapter + verification + `alerts.deliver` wiring; triage module starts | `RiskResult` exact; every outbound text verified |
| **D2** | triage module + aliases + all four verdicts | verdicts correct on fixtures |
| **D3** | triage tab + old-footage + adversarial tests | demo shows all four verdicts |
| **D3** | `scripts/11_layers_demo.py` | offline end-to-end demo |
| **D3 (stretch)** | WhatsApp text channel + dry-run payload | JSON payload, zero network calls |
| **D3 (stretch)** | one live WhatsApp text | a real phone receives it; may be cut |

**Cut order, highest first:** live WhatsApp send → WhatsApp channel (keep the
dry-run payload) → triage tab → old-footage detection → Urdu template (keep
English) → messages module (inline the English template) → escalation-only
mode. **Never cut:** verification, CI, the adapter contract.

Delivery is **off the critical path**. It starts only after the D3 demo runs
end-to-end offline. If Meta is not ready, the demo shows the exact provider
payload instead of a live send.

Do not start triage before the D2 gate. It reads the latest run's levels;
without a fused run it can only return `CANNOT_ASSESS`.

### 8.10 Known blockers before this plan can be executed

> The first two rows and the `runner._to_predictions` row describe the **deleted
> prototype**. A from-scratch build (§9) avoids them by creating the
> northern-eight config and a correct runner from the first commit. The
> remaining rows — Urdu review, advisories, Meta credentials, template approval
> and token handling — apply to any build.

| Blocker | Effect | Fix |
|---|---|---|
| `configs/basins.yaml` still lists the old Peshawar set (`kabul_*`, `kohat_*`, `gomal_*`) | The adapter sees the configured basins; triage on the northern eight has no level and returns `CANNOT_ASSESS` | Replace the config with the northern eight and regenerate the demo data; do this before the triage demo |
| `configs/region.yaml` still says `kp-peshawar` | Report and app name disagree with the domain | Same commit as the basin fix |
| Urdu aliases and templates are unverified | Wrong spelling or tone in a public demo | Native-speaker review before D3 |
| `data/advisories.json` has no verified entries | `SUPPORTED` is only reachable with a labelled demo advisory | Hand-curate PDMA / NDMA / PMD links; never scrape or invent |
| `runner._to_predictions` reads `rain_mm_3h` from the prediction frame | The baseline path raises `KeyError` before any layer runs | Fix before D1; the layers cannot be demonstrated on a broken run |
| No Meta app, phone number ID, token or verified test recipient | WhatsApp send cannot be attempted at all | Create the app and verify the demo phone on D1; if not ready by D3, cut live WhatsApp |
| WhatsApp template approval is outside the team's control | Free-form text only works inside the 24 h window | Message the business number first, or cut to the dry-run payload |
| Token handling | A pasted token in a log or report is a leak | Env vars only; redact; CI `secrets` job |

### 8.11 Demo delivery: short alert text via WhatsApp (stretch, plan only)

**Scope.** One **demo recipient**, not a subscriber system. `delivery: file`
stays the default and shadow mode is unchanged. The demo sends the verified
alert as a **WhatsApp text message** — no image, no SMS gateway, no public URL.
This is the SMS-style message delivered over WhatsApp; WhatsApp and SMS are
separate networks, so WhatsApp cannot fall back to SMS if the recipient is not
on WhatsApp.

**Why text only.** The text is the artefact the verifier already approves.
Sending it directly removes a second rendering path that could disagree with
it, and removes Pillow, fonts, image hosting and MMS from the sprint. A card
image is a later option, not this plan.

**Cut rule.** If Meta credentials are not ready by D3, this section is cut in
full and the demo shows the dry-run payload instead of a live send.

#### 8.11.1 Channel decision

| Channel | What it carries | Verdict |
|---|---|---|
| **WhatsApp text** | the verified message body | **This plan**; needs Meta app, token and a verified recipient |
| WhatsApp image + caption | PNG plus the verified text | Optional later; adds Pillow, a renderer and media upload |
| SMS | text | Not used here; separate gateway, sender ID and per-message cost |
| WhatsApp → SMS fallback | — | **Not possible**; the two networks are separate |

The delivered text is identical to the in-app alert and the `outbound.json`
record. Nothing is reformatted for WhatsApp.

#### 8.11.2 Files

| File | Purpose |
|---|---|
| `src/floodwatch/channels/__init__.py` | `send(result, action, text, *, cfg) -> DeliveryResult` dispatch and gating |
| `src/floodwatch/channels/whatsapp.py` | send one text message through the Cloud API |
| `tests/test_channels.py` | payload shape, gating, failure handling (all mocked) |

No new runtime dependency: use `urllib.request` from the standard library. No
Pillow, no image host, no SMS SDK.

#### 8.11.3 Message body

The body is exactly the string `messages.format_alert` or
`messages.format_all_clear` produced and `verify.check_risk_alert` approved.
It already contains the basin id, one level word, the reason, `computed_at`
and Rescue 1122.

- Keep it under 1600 characters. WhatsApp's own limit is higher, but the
  message is deliberately SMS-short so the same text could be sent by SMS
  later without rewriting it.
- No URL, attachment, image or second sentence is added by the channel layer.
- `computed_at` is the run timestamp, never wall clock, so a replay is dated
  correctly.
- Urdu stays available in-app; the demo send is English.

#### 8.11.4 Gating — three locks, all required

```
delivery: file                  -> write the payload only (default)
delivery: whatsapp              -> still no send
+ FLOODWATCH_SEND=1             -> send to the single configured recipient
```

Additional guards:

- One `WHATSAPP_TO` recipient; there is no subscriber list and no consent
  store.
- Hard per-run cap of 5 outbound messages; exceeding it is an error, not a loop.
- `--dry-run` writes `outbound_payload.json` with the exact provider request
  body, so the payload can be inspected without a send.
- Credentials come from environment variables only: `WHATSAPP_TOKEN`,
  `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`. They are never written to
  `run_report.json`, `outbound_payload.json` or logs.

#### 8.11.5 WhatsApp specifics (must be confirmed against Meta's docs)

- Send with `POST /{phone_number_id}/messages` and
  `{"messaging_product": "whatsapp", "to": ..., "type": "text",
  "text": {"body": ...}}`.
- Free-form text is only allowed **inside the 24 h customer-service window**.
  Outside it, use an approved **text template** with the alert as a body
  parameter. A text template is easier to approve than an image template.
- The Meta test number can only message a small list of **verified
  recipients**. Add the demo phone on day 1; verification is not instant.
- A template's body parameters must match the verifier's allowed numbers; do
  not let Meta's placeholder text add a number the verifier did not approve.
- Template approval timing is outside the team's control. **If it is not
  approved by D3, use the 24 h window or cut the live send.**

#### 8.11.6 Why there is no SMS branch

SMS is a separate network with its own gateway, sender ID, per-message cost and
delivery receipts. WhatsApp cannot send an SMS, and this sprint does not buy an
SMS account. If an SMS channel is added later, it sends the same verified text
without an image; it is not part of this plan.

#### 8.11.7 Failure behaviour

A send failure is **never** allowed to crash the run or block the alert file:

- `alerts.json` and `outbound.json` are written first.
- Each send returns `{channel, attempted, ok, provider_id, error, latency_ms}`.
- `run_report.json` gets `delivery: {mode, attempted, sent, failed, skipped}`.
- Any exception is caught per message, recorded, and the run continues.
- A timeout is not retried in a loop during the demo.

#### 8.11.8 Feasibility — what is verified and what is not

| Claim | Status |
|---|---|
| WhatsApp accepts a text message | **Documented by Meta**; needs the app, token and a verified recipient to prove |
| A live WhatsApp send works | **Not verifiable here** — no credentials, no verified phone |
| The same text could be sent by SMS later | **Yes**, but it needs a separate gateway; not in this plan |
| WhatsApp can send an SMS | **No** — different networks |
| Suitable as an operational warning channel | **No** — no queue, retries, receipts, opt-in or on-call |

**Effort.** Channel + gating 1 h · tests 45 min ≈ **1.5 h**, plus Meta setup on
D1. This is the last item before the cut line.

**Acceptance.**
- [ ] `--dry-run` writes `outbound_payload.json` with the exact text request and
      makes zero network calls.
- [ ] `delivery: file` makes zero network calls (asserted by a mocked socket).
- [ ] `delivery: whatsapp` without `FLOODWATCH_SEND=1` sends nothing.
- [ ] The request body has `type: text`, the configured recipient, and the
      verified body unchanged.
- [ ] A blocked draft is never sent.
- [ ] A mocked 500 / timeout is recorded as `failed` and the run still exits 0.
- [ ] Tokens never appear in `run_report.json`, logs or `outbound_payload.json`.
- [ ] The per-run cap of 5 is enforced.
- [ ] No image, SMS SDK or public URL is used anywhere in the path.
- [ ] *(demo day)* One live text reaches the test recipient.

### 8.12 Definition of done for §8

- [ ] Adapter tests pin the tier→level table and the one-row-per-basin rule.
- [ ] Alert decisions produce one alert per crossing, one per escalation, one
      per cooldown expiry, and exactly one all-clear.
- [ ] Every outbound message passes `check_alert`; a planted error is blocked.
- [ ] `run_report.json` has `verify.blocked` and a decision summary.
- [ ] Triage reaches all four verdicts, never says "fake", and is deterministic.
- [ ] Old footage is downgraded and the date is cited.
- [ ] CI is green; `requirements.txt` exists.
- [ ] `configs/split.yaml`, the prediction contract and shadow mode are untouched.
- [ ] The demo runs offline from a committed run directory.
- [ ] *(stretch)* `--dry-run` writes `outbound_payload.json` with zero network
      calls.
- [ ] *(stretch)* One live WhatsApp text reaches the test recipient.
- [ ] *(stretch)* A provider failure is recorded and the run still exits 0.
- [ ] *(stretch)* Tokens appear in no report, log or payload file.

---

## 9. Build from scratch — even split by model

> **Starting point: an empty folder.** `D:\floodwatch` contains only `PLAN.md`
> and this backlog. There is no `src/`, `tests/`, `configs/`, `data/`,
> `models/`, `runs/`, app or git history. Everything below is created from
> zero. The file paths are targets, not existing files.

### 9.0 The target and the two models

A thin FloodWatch that runs end to end:

```
Open-Meteo -> features -> windows ┬-> Model A: CNN-LSTM (cloudburst) ┐
                                  └-> Model B: LSTM     (snowmelt)   ├-> fusion -> tiers
                                                                     ┘
fusion -> runner -> predictions_fused.parquet + run_report.json
       -> adapter -> decisions -> messages -> verify -> alerts
       -> Streamlit app
       -> optional WhatsApp text
```

**Model A — cloudburst, owned by Qamran. CNN-LSTM, as in the original
procedure.** A hybrid over a 72-hour per-basin window with two branches:

- **Spatial branch:** a small 2D CNN over a 3×3 Open-Meteo grid patch around
  each basin (rain, temperature and freezing level per cell) plus static
  terrain channels (elevation, slope, terrain susceptibility). Two convolution
  blocks and global average pooling produce a patch embedding.
- **Temporal branch:** an LSTM over the 72-hour basin-mean series: rain 1 h /
  3 h / 24 h / 72 h, forecast 6 h, temperature, freezing level, soil moisture
  and terrain susceptibility.
- **Fusion:** concatenate the CNN embedding and the LSTM final hidden state,
  then a dense layer and one sigmoid output.

Guardrails: at most 2 conv blocks / 32 filters and 1 LSTM layer / 64 units;
dropout and early stopping are mandatory; CPU only; fixed seed.

**Substitution, stated openly.** The PDF's spatial branch uses IMERG rainfall
and Meteosat cloud imagery. The prototype builds the patch from Open-Meteo
multi-point queries instead, so the 3-day build needs no NASA or EUMETSAT
account. The structure (spatial CNN + temporal LSTM + concatenation head) is
kept; the input source is substituted. `docs/model_a.md` and `docs/SOURCES.md`
must say so.

**Model B — snowmelt, owned by Warisha.** A small LSTM over the same 72-hour
window but a different feature emphasis: temperature, freezing level, snow
depth, degree-day melt and rain-on-snow. One layer, 32–64 units, one sigmoid
output. The original procedure lists snowmelt as a **v2** module and recommends
a degree-day or simple hydrological model plus gradient boosting before deep
learning. The prototype pulls B forward as the second mechanism and keeps the
degree-day baseline as the mandatory fallback: if the LSTM does not beat it on
validation, fusion uses the baseline and the report says so.

Both models predict the same label: **a flood event in the next 6 hours**,
defined once in `schema.py` and frozen. Both use the same chronological split,
the same window builder and the same evaluation harness. They never import each
other. Fusion is the only place their outputs meet. Both mechanisms run on
every basin; no model is gated per basin.

**Prototype deviations from the PDF, recorded once:**

- The PDF's Module A target is 30–120 minutes and a 15-minute run rate. The
  prototype uses a shared 6-hour label and an hourly run rate so A and B can be
  fused on one grid from hourly Open-Meteo data. This is a prototype
  limitation, not the operational target.
- Module D (gauge propagation) is **out of scope** for this 3-day build.
- Storage is Parquet + JSON; Zarr/NetCDF, PostGIS and DVC are out of scope.
- The full alignment table is §9.12.

**Be honest about the risk.** Eight basins and a few years of hourly data is a
small, highly autocorrelated dataset. A deep model can overfit and still look
good on a random split. Guardrails: small models, dropout, early stopping on
validation, a chronological split with a 30-day gap, basin-grouped checks, and
a non-deep baseline for each mechanism. Every model card reports validation
metrics and the baseline side by side. If a deep model loses to its baseline,
fusion uses the baseline and the report says so; the deep path is never
silently removed.

Target tree:

```
floodwatch/
├── app/streamlit_app.py
├── configs/{basins,region,thresholds,split}.yaml
├── data/{demo,static,state}/
├── docs/{FEATURE_BACKLOG.md,SOURCES.md,model_a.md,model_b.md}
├── scripts/01_fetch_openmeteo.py ... 11_layers_demo.py
├── src/floodwatch/
│   ├── schema.py  config.py  features.py  thresholds.py
│   ├── data_sources/{openmeteo.py,grid.py,cache.py}
│   ├── models/{base.py,windows.py,model_a.py,model_b.py,eval.py}
│   ├── models/artifacts/{model_a.pt,model_b.pt}
│   ├── fusion.py  runner.py
│   ├── interop.py  decisions.py  messages.py  verify.py
│   ├── triage.py  explain.py  alerts.py
│   └── channels/{__init__.py,whatsapp.py}
├── tests/
├── .github/workflows/ci.yml
├── requirements.txt  pyproject.toml
└── README.md
```

Dependencies: `pandas`, `numpy`, `scikit-learn`, `pyarrow`, `torch` (CPU wheel),
`streamlit`, `requests`, `PyYAML`, `pytest`, `ruff`. **Not** pydantic, SQLite,
Gradio, an LLM, IMERG or Meteosat. `torch` is the only heavy dependency; CI
installs the CPU wheel and caches it.

### 9.1 Even split — about 17.5 hours each

Shared M0, both: `git init`, skeleton, branch protection, contract freeze
(1 h each).

**Qamran (A) — cloudburst path, data, verification.**

| Work | Files | Est. |
|---|---|---|
| Configs, split, fixture | `configs/*`, `data/demo/` | 1.5 h |
| Open-Meteo ingest + cache + grid patch | `data_sources/` | 3.5 h |
| Features + window builder (spatial patch + temporal sequence) | `features.py`, `models/windows.py` | 3.0 h |
| **Model A: CNN-LSTM** | `models/model_a.py`, `scripts/03_train_a.py` | 6.0 h |
| Verification | `verify.py`, `tests/test_verify.py` | 1.0 h |
| Triage + aliases | `triage.py`, `data/static/basin_aliases.json`, `data/advisories.json` | 2.0 h |
| Provenance + model card | `docs/SOURCES.md`, `docs/model_a.md` | 0.5 h |
| **Total** | | **17.5 h** |

**Warisha (B) — snowmelt path, fusion, adapter, delivery, UI.**

| Work | Files | Est. |
|---|---|---|
| Repo + CI + dependencies | `.github/workflows/ci.yml`, `requirements.txt`, `pyproject.toml`, `.gitignore`, `.env.example` | 1.5 h |
| Model contract + eval harness | `models/base.py`, `models/eval.py` | 1.5 h |
| **Model B: LSTM** | `models/model_b.py`, `scripts/04_train_b.py` | 4.0 h |
| Fusion + thresholds | `fusion.py`, `thresholds.py` | 2.0 h |
| Runner + report | `runner.py` | 1.5 h |
| Adapter | `interop.py`, `tests/test_interop.py` | 1.0 h |
| Decisions + messages | `decisions.py`, `messages.py` | 1.5 h |
| Explain | `explain.py` | 1.0 h |
| App | `app/streamlit_app.py` | 2.0 h |
| Alerts + WhatsApp | `alerts.py`, `channels/` | 1.0 h |
| State | `data/state/area_state.json` (gitignored) | 0.25 h |
| Model card | `docs/model_b.md` | 0.25 h |
| **Total** | | **17.5 h** |

Estimates include the unit tests for the listed files.

The split is even by hours, not by prestige. Qamran carries the data pipeline
and the CNN-LSTM; Warisha carries the LSTM, the fusion, the adapter and every
delivery surface. If one side runs ahead, they take a cut-line item from the
other, never a file.

**One writer per shared file:**

| File | Writer | Reader | Rule |
|---|---|---|---|
| `schema.py` | Qamran | Warisha | Frozen D1 11:00; joint PR to change |
| `features.py`, `models/windows.py` | Qamran | Warisha | One feature/window implementation; no forks |
| `models/base.py`, `models/eval.py` | Warisha | Qamran | One output contract and one metric harness |
| `configs/*` | Qamran | Warisha | Read-only for Warisha |
| `models/model_a.py`, `model_a.pt` | Qamran | Warisha (via parquet) | Warisha never imports or edits |
| `models/model_b.py`, `model_b.pt` | Warisha | Qamran (via parquet) | Qamran never imports or edits |
| `fusion.py`, `runner.py`, `interop.py` | Warisha | Qamran | Qamran reads the report only |
| `verify.py`, `triage.py` | Qamran | Warisha | Warisha reads |
| `app/`, `decisions.py`, `messages.py`, `explain.py`, `alerts.py`, `channels/` | Warisha | Qamran | Qamran reads |
| `requirements.txt`, `pyproject.toml` | Warisha | Qamran | Qamran requests |
| `data/demo/`, `runs/demo/` | Qamran | Warisha | Read-only for Warisha |
| `docs/FEATURE_BACKLOG.md` | Warisha | Qamran | Plan frozen after D1; Qamran sends changes |

### 9.2 Freeze these on D1 at 11:00

Both stop and agree before feature code. A change after the freeze is a joint
PR with a one-line note.

1. **Prediction contract** (`schema.py`): `basin_id`, `timestamp_utc`,
   `module`, `prob`, `tier`, `top_drivers`. Additive only. `module` is
   `A_cloudburst_cnn_lstm` or `B_snowmelt_lstm`.
2. **Label**: flood event in the next 6 hours; horizon, event definition and
   negative-sampling rule in `schema.py`. Neither model may redefine it.
3. **Feature schema** (`features.py`): column names, units, null policy and
   aggregation windows.
4. **Window spec** (`models/windows.py`): lookback 72 h, stride 1 h, one
   temporal sequence plus one static spatial patch per sample, which columns,
   scaler fit on train only, no window crossing a split boundary.
5. **`ModelOutput`** (`models/base.py`): `prob`, `top_drivers`,
   `model_version`, `trained_at`, `baseline_prob`, `metrics`.
6. **Evaluation harness** (`models/eval.py`): POD, FAR, CSI, PR-AUC, event POD
   and median lead time; validation only; identical for A and B.
7. **`run_report.json`**: `verify`, `decisions`, `sources`, `delivery`,
   `models: {a, b}`.
8. **`configs/basins.yaml`**: the northern eight. **`configs/split.yaml`**:
   train / validation / test years and the 30-day gap, frozen.
9. **Fixture**: `data/demo/features_demo.parquet`, synthetic and labelled, so
   both models and the app can be built before real data.
10. **Public tier mapping**: `none`/`low` → no public alert, `moderate` →
    Watch, `high` → Warning, `severe` → Emergency. The six-column schema keeps
    its five internal tiers; the three public words follow the PDF.

The fixture is a pipeline test, not a scientific result. It is replaced by the
real run on D2 and never tuned to look good.

### 9.3 Model separation rules — CNN-LSTM vs LSTM

These are the rules that stop the two models from colliding. They apply to both
people.

1. **One model, one file.** `model_a.py` and `model_b.py` never import each
   other. Shared code lives only in `models/base.py`, `models/windows.py` or
   `models/eval.py`.
2. **One checkpoint, one path.** `models/artifacts/model_a.pt` and
   `model_b.pt`. No overwriting, no shared filename, no `latest.pt`.
   Checkpoints are gitignored unless a demo checkpoint under 20 MB is
   explicitly committed.
3. **One training script each.** `scripts/03_train_a.py` and
   `scripts/04_train_b.py`. Each writes its own metrics file and its own
   prediction parquet (`predictions_a.parquet`, `predictions_b.parquet`).
4. **Same features, not forked features.** Both read the same feature table
   from `features.py` and the same windows from `models/windows.py`. Each model
   may select its own column subset (CNN-LSTM: rain, grid patch and terrain;
   LSTM: temperature and snow), but the table, timestamps, scalers and split
   are shared. If the LSTM needs a new column, Warisha requests it; Qamran adds
   it with a test. Warisha does not copy the feature code into `model_b.py`.
5. **Same label, same split.** The 6-hour horizon, event definition, years and
   30-day gap are frozen. A model that changes the label is not comparable and
   is rejected.
6. **Same output shape.** Both return `ModelOutput`. Fusion joins on
   `(basin_id, timestamp_utc)` and asserts the grid is identical. A missing
   timestamp is a bug, not a zero.
7. **Same evaluation.** Both call `models/eval.py`. No private metric, no
   different rounding, no cherry-picked threshold. Each model card shows the
   baseline next to the deep model.
8. **No leakage.** Scalers and imputers fit on train only. Windows never cross
   a split boundary. No feature computed from the label or from the future.
   `tests/test_windows.py` asserts both.
9. **Determinism.** Fixed seed, CPU, deterministic ops where PyTorch allows;
   save the seed and the data snapshot hash with the checkpoint. Two runs on
   the same data must produce the same validation table.
10. **Baseline required.** Model A ships a logistic-regression baseline; Model
    B ships a degree-day baseline. If the deep model loses on validation,
    fusion uses the baseline and the report says so. The deep path stays
    visible.
11. **Small models only.** A: at most 2 conv blocks / 32 filters and 1 LSTM
    layer / 64 units. B: at most 2 LSTM layers and 64 units. Dropout and early
    stopping are mandatory. A model that needs a GPU is out of scope.
12. **One owner reviews the other's model card.** Qamran reviews
    `docs/model_b.md`; Warisha reviews `docs/model_a.md`. The card lists data
    snapshot, features, hyperparameters, validation metrics, baseline metrics
    and known failure modes.
13. **No editing the other model.** If you think the other model is wrong, open
    an issue or a PR comment. Never change its file, checkpoint, script or
    test.
14. **Fusion reads outputs, not internals.** Warisha's `fusion.py` reads the
    two prediction parquets. It does not import `model_a.py` or `model_b.py`,
    and it does not retrain either model.
15. **Contract changes need both approvals.** `schema.py`, `models/base.py`,
    `models/windows.py`, `models/eval.py`, `configs/split.yaml` and the
    `run_report.json` keys are joint PRs.
16. **No model uses the other's output as a feature.** The two mechanisms are
    independent evidence; fusion combines them. A model that peeks at the other
    model's probability is not a second mechanism.

**Model card template** (`docs/model_a.md`, `docs/model_b.md`): data snapshot
hash, label horizon, window spec, feature list, architecture, hyperparameters,
seed, validation metrics (POD, FAR, CSI, PR-AUC, event POD, median lead time),
baseline metrics, calibration notes, known failure modes and the exact command
to reproduce the validation table.

### 9.4 Build order

| # | Milestone | Owner | Done when |
|---|---|---|---|
| M0 | Skeleton, CI, contracts, fixture | both | `pytest` runs; CI green; fixture validates |
| M1 | Open-Meteo + grid patch + cache + features + windows | Qamran | real values for 3 basins; windows pass leakage tests |
| M2a | **Model A: CNN-LSTM** + baseline + model card | Qamran | validation table with CNN-LSTM and logistic |
| M2b | **Model B: LSTM** + baseline + model card | Warisha | validation table with LSTM and degree-day |
| M3 | Fusion + thresholds + runner | Warisha | `runs/demo/` end to end, both models joined |
| M4 | Adapter, decisions and messages | Warisha | `RiskResult` exact; texts deterministic |
| M5 | Verify and triage (Qamran) + explain and alerts (Warisha) | Qamran / Warisha | every text verified; four verdicts |
| M6 | App + replay + ablation + WhatsApp + demo | both | offline demo; live send optional |

M2a and M2b run in parallel from D1 afternoon. Neither waits for the other:
both train on the fixture, then on real data when M1 lands.

### 9.5 Day plan

**D1, first 30 minutes, both:** `git init`, first commit, branch protection,
agree on the tree. Then split.

| When | Qamran (A) — CNN-LSTM | Warisha (B) — LSTM | Gate |
|---|---|---|---|
| **D1 morning** | Package, `schema.py`, configs, label, fixture | CI, deps, `models/base.py`, `models/eval.py`, app shell | Contracts frozen 11:00; CI green |
| **D1 afternoon** | Open-Meteo + grid patch + cache + features + windows | LSTM dataset on fixture; baseline; decisions/messages | Features work; both models can train |
| **D2 morning** | Train and tune CNN-LSTM; validation table; model card | Train and tune LSTM; validation table; model card | Both models produce `ModelOutput` on the same grid |
| **D2 afternoon** | Verify; triage start | Fusion + thresholds + runner + adapter; first fused run | End-to-end run on real or fixture data |
| **D3 morning** | Triage finish; replay/ablation support | App; explain; verify tab | App reads the run; verdicts reachable |
| **D3 afternoon** | Demo support; model card polish | Alerts + WhatsApp dry-run; layers demo; README | Freeze 15:00; rehearse 16:00 |

**Merge windows:** 12:30 and 17:00. Anything not merged by 17:00 stays on its
branch and is finished the next morning.

If data slips, both models train on the fixture and the demo is labelled
synthetic. If one model slips, fusion uses that mechanism's baseline and the
report says so. The demo run is the only hard handoff, scheduled for D2
afternoon.

### 9.6 Conflict-avoidance rules — both people

1. **One file, one owner.** Need a change elsewhere? Small PR with the exact
   diff, or ask. Never edit directly.
2. **Branch per task:** `qamran/<topic>` and `warisha/<topic>`. Never commit to
   `main`.
3. **Rebase on `main` before opening a PR.** Squash merge. Delete the branch.
4. **PR size:** one feature or ≤ 400 changed lines. The other person reviews;
   no self-merge.
5. **Contract PRs need both approvals:** `schema.py`, `models/base.py`,
   `models/windows.py`, `models/eval.py`, `configs/`, `run_report.json` keys.
6. **No drive-by formatting** in a file you do not own.
7. **Never disable a failing test to merge.** Fix it, or `xfail` with a linked
   issue and the other person's agreement.
8. **Dependencies are Warisha's.** Qamran requests; Warisha edits
   `pyproject.toml` / `requirements.txt` and updates the lockfile if one is
   used.
9. **Configs, fixture and demo run are Qamran's.** Read-only for Warisha.
10. **Secrets stay out of git.** `.env` ignored; Warisha owns `.env.example`;
    no token in a PR, issue or log.
11. **Blocked 30 minutes?** Send the exact error, file and what you tried.
12. **Two stand-ups:** 09:30 and 17:30 — done, next, blocked, contract changes.
13. **The plan is the shared truth.** If it is not in a PR or this document, it
    did not happen.
14. **Handoff is runnable.** Each day the other person can run `pytest` and the
    demo from a clean clone.
15. **If one person is ill or blocked,** the other runs the cut line in §9.9.
    Verification, CI and the prediction contract are never cut.

### 9.7 Blocker ownership

| Blocker | Owner | Deadline | Fallback |
|---|---|---|---|
| No data yet | Qamran | D1 afternoon | synthetic fixture |
| Feature/window contract changes late | Qamran | D1 11:00 | stop and freeze it |
| CNN-LSTM overfits or underfits | Qamran | D2 12:00 | smaller CNN-LSTM, dropout, early stopping, logistic baseline |
| Grid patch slow or rate-limited | Qamran | D1 afternoon | 3×3 patch, cache; fall back to basin-mean and document it |
| LSTM overfits or underfits | Warisha | D2 12:00 | smaller LSTM, dropout, early stopping, degree-day baseline |
| PyTorch install or CI slow | Warisha | D1 morning | CPU wheel + cache; pin the version |
| Model grids do not join | both | D2 12:00 | assert on `(basin_id, timestamp_utc)`; rebuild windows |
| No fused run | Warisha | D2 18:00 | Qamran codes against `stub_result()` and the frozen report shape |
| Empty `data/advisories.json` | Qamran | D3 | labelled `DEMO` advisory or `CANNOT_ASSESS` |
| No Meta credentials | Warisha | D1 | dry-run payload |
| No Urdu review | Warisha | D3 | English-only demo |

### 9.8 Hard "do not touch" lists

**Qamran must not edit:** `models/model_b.py`, `models/artifacts/model_b.pt`,
`scripts/04_train_b.py`, `tests/test_model_b.py`, `models/base.py`,
`models/eval.py`, `fusion.py`, `thresholds.py`, `runner.py`, `interop.py`,
`app/streamlit_app.py`, `decisions.py`, `messages.py`, `explain.py`,
`alerts.py`, `channels/`, `.github/`, `requirements.txt`, `pyproject.toml`,
`data/state/`, `docs/model_b.md`, `docs/FEATURE_BACKLOG.md`, `README.md`.

**Warisha must not edit:** `data_sources/`, `features.py`, `models/windows.py`,
`models/model_a.py`, `models/artifacts/model_a.pt`, `scripts/03_train_a.py`,
`tests/test_model_a.py`, `tests/test_windows.py`, `configs/`, `verify.py`,
`triage.py`, `scripts/01_*` … `scripts/09_*`, `data/demo/`,
`runs/demo/`, `data/static/`, `data/advisories.json`, `docs/SOURCES.md`,
`docs/model_a.md`.

**Neither person may:** change `configs/split.yaml`, change the 6-hour label,
re-run the test split, change the six-column prediction contract or the
`ModelOutput` shape without a joint PR, or claim a synthetic metric is a
scientific result.

### 9.9 Cut line

1. Live WhatsApp send (keep the dry-run payload).
2. Urdu template (keep English).
3. Triage tab (keep the CLI).
4. Old-footage detection.
5. Source-health panel.
6. Ablation table.
7. Map (keep the table).
8. Deep-model refinement — fall back to that mechanism's baseline, keep the
   deep path in the report.

**Never cut:** the prediction contract, one working model per mechanism,
fusion, the runner, the app, verification, CI, the offline demo run.

### 9.10 Why this split is even

- Both people own one model end to end: data contract → training → validation
  table → model card. Neither is a spectator on the modelling.
- The crossing points are small and frozen: one feature table, one window
  builder, one `ModelOutput`, one evaluation harness, one split.
- The models never import each other. Fusion is the only join, and it reads
  parquets, not code.
- The hours are balanced at roughly 17.5 vs 17.5. If one side finishes early,
  they take a cut-line item, not the other person's file.
- CI and the contract belong to the person who does not own the cloudburst
  model, so the contract is enforced by someone with no incentive to loosen it.

### 9.11 Note on §8.10

The prototype-specific rows in §8.10 (config drift and the `rain_mm_3h`
`KeyError`) are **not inherited**: a from-scratch build creates the
northern-eight config and a correct runner from the start. The delivery and
review blockers in that table still apply. If the old repository is restored
instead of rebuilt, §8.10 applies in full and this section reverts to the
"add features" split.

### 9.12 Alignment with the original procedure

Source: `KP_Flash_Flood_Project_Procedure_v2.pdf` (15 pages). The PDF is the
project-level plan; §9 is the 3-day prototype built from it. Where they differ,
the difference is deliberate and must be repeated in the model card and README.

| Area | Original PDF | This prototype | Why |
|---|---|---|---|
| Model A architecture | CNN-LSTM: spatial CNN branch + temporal LSTM branch, fused | CNN-LSTM: 2D CNN over an Open-Meteo grid patch + terrain, LSTM over the 72 h series, concatenation head | Structure kept; inputs substituted for a 3-day build |
| Model A spatial inputs | IMERG rainfall, Meteosat cloud imagery, ERA5, DEM, local sensors | Open-Meteo multi-point grid patch, basin series, static terrain | No NASA/EUMETSAT accounts; no field sensors |
| Model A lead time | 30–120 min | 6 h shared label | One label so A and B fuse on one grid; documented limitation |
| Run rate | Every 15 min | Hourly | Source data is hourly; 15 min adds no information |
| Model B | v2; degree-day / simple hydrological + gradient boosting first | v1 prototype; LSTM + degree-day baseline | Two mechanisms in 3 days; baseline is the fallback |
| Module D | v1; gauge propagation | Out of scope | No gauge feed in 3 days; next milestone |
| Tiers | Watch / Warning / Emergency | Five internal tiers mapped to the three public words | Keeps the frozen six-column schema |
| Storage | Zarr/NetCDF, PostgreSQL+PostGIS, DVC | Parquet + JSON | 3-day prototype |
| UI | Gradio or Streamlit prototype | Streamlit | Allowed by the PDF |
| Data sources | IMERG, ERA5, Meteosat, MODIS, Sentinel, DEM, gauges | Open-Meteo + static terrain | Prototype; `docs/SOURCES.md` lists the operational upgrade |

**What this means for the demo.** The prototype proves the pipeline, the two
mechanisms, the fusion, the trust layer and the app. It does not claim the
operational coverage or lead time in the PDF. The model cards, README and the
demo must state the substitutions; a synthetic metric is never presented as a
scientific result.
