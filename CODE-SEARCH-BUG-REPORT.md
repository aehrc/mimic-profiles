# code-search: intermittent `"No response from agentic evaluator"`, cached permanently

**Status:** draft bug report for the code-search authors
**Reported by:** Felix Naumann (CSIRO)
**Date observed:** 2026-08-10
**Service:** `code-search` at `http://localhost:3000`, recently updated to a newer version
**Terminology server:** `https://velonto.dw.csiro.au/fhir` (Ontoserver; SNOMED CT AU edition, module `32506021000036107`)

---

## 1. Summary

`POST /api/v1/find-code` intermittently returns **HTTP 200** with an empty result:

```json
{"matches": [], "reasoning": "No response from agentic evaluator"}
```

Three problems:

1. **It is a distinct failure state, not a no-match — but only an undocumented string says so.** When the agentic search genuinely looks and finds nothing it reports `"Agentic eval matched 0 candidate(s) after N tool call(s)"`, which names the outcome and the work done. Over a full 1,201-code run the two populations separate cleanly: **203 of 241** empty results carry the informative message, while **all 30** of the others carry `"No response from agentic evaluator"` and nothing else. Both arrive as HTTP 200 with `matches: []`, so a caller can only tell them apart by substring-matching free text.
2. **The failure is cached, in two tiers, and outlives every obvious recovery.** It is stored like a successful result: an in-memory LRU with a 2-hour TTL, checked *before* a SQLite table (`resolutions` in `code-search.db`). So an in-process retry is useless, a service restart clears only the memory tier, and deleting the database row leaves the memory tier serving the stale answer for up to two hours. Recovering one poisoned label requires **both** a row delete and a restart.
3. **It is frequent**: ~10% of calls in a serial 20-call arm, **30 of 1,201 (2.5%)** in a full production run, and `result_code:null` on **39 of 135 agentic calls (29%)** in the log overall.

The practical consequence is that a caller either records "no SNOMED concept exists" for a code that was never successfully evaluated, or — as ours does — treats it as an error and discards work. **There is no machine-readable way to make that choice correctly**, and that is the crux of this report.

**It is not a timeout, not a concurrency problem, not caused by unusual input, and not a provider or transport error.** Section 4 gives the black-box measurements and section 5 the log evidence.

> **Correction from an earlier draft of this report.** We initially concluded the message was a misnomer for an ordinary no-match, on the strength of server-log rows showing the loop running 10–13 rounds and burning real tokens rather than erroring (section 5). That evidence is real but was incomplete: we had never captured a *legitimate* empty result to compare against. Once we did, the two proved cleanly distinguishable, and the "misnomer" reading was wrong. We also mis-stated the cache key as punctuation-insensitive; per source it is `lower(text) + "||" + url + "||" + scope` with whitespace runs collapsed, so **punctuation does bust the key** and a hyphen-for-space edit is a genuinely fresh call.

---

## 2. Impact on the consuming project

A terminology mapping pipeline calls `find-code` once per source code to build a committed mapping table. A run over **1,201 codes at 8 workers produced 30 of these failures**. The generator treats them as errors and refuses to write the table, so the entire run was discarded — including the ~1,171 successful calls, which cannot be salvaged because the 30 failures are now cached and a re-run reproduces them instantly.

Had the generator instead trusted the empty result, it would have committed 30 codes as "no SNOMED concept exists" — a false, published, auditable-looking claim about clinical terminology.

---

## 3. Reproduction

### Request

```http
POST http://localhost:3000/api/v1/find-code
Content-Type: application/json

{
  "text": "<label>",
  "url": "http://snomed.info/sct?fhir_vs=ecl/%3C%3C105590001",
  "system": "http://snomed.info/sct",
  "max_candidates": 1,
  "effort": "balanced"
}
```

The constraint is the SNOMED CT implicit ValueSet for ECL `<<105590001 |Substance|`, which expands to **29,670 concepts** on this server.

### Inputs that triggered it

Labels are FDB **Enhanced Therapeutic Classification** (ETC) class names and FDB **Generic Sequence Number** (GSN) drug names, taken from the MIMIC-IV FHIR IG CodeSystems `mimic-medication-etc` (1,201 concepts) and `mimic-medication-gsn` (9,347 concepts).

Confirmed failing (server-returned `"No response from agentic evaluator"`, at **concurrency 1**):

| label | latency |
|---|---|
| `Immunomodulator B-Lymphocyte Stimulator (BLyS)-Specific Inhibitors MCAB` | 68.23 s |
| `Contraceptives - Intravaginal, Systemic - Estrogen and Progestin Combs.` | 35.99 s |

From the earlier 1,201-code run at 8 workers, 5 of the 30 (the rest were not printed):

```
NSAID Analgesics (COX Non-Specific) - Propionic Acid Derivatives
Antihyperglycemic-Dipeptidyl Peptidase-4(DPP-4)Inhibitor and Biguanide
BPH Agent- 5-alpha Reductase Inhib and alpha-1 Adrenoceptor Antag Comb
Urinary Antispasmodic - Anticholinergics, Non-Selective
Asthma/COPD Tx - Beta-adrenergic-Anticholinergic-Glucocorticoid comb,
```

**Note:** these strings are now poisoned in that instance's cache and will return the failure instantly until the service is restarted, so they cannot be used to reproduce a *fresh* failure on that instance.

### Caching behaviour, and how to observe it

- A poisoned label returns in **~0.0 s** with the failure body; an unpoisoned one takes seconds to minutes.
- **Cache key** (read from `src/core/cache.ts` and `search-loop.ts`):
  `normaliseKey(text) + "||" + (context ?? url) + "||" + scopeKey(scope)`, where `normaliseKey` lowercases and collapses whitespace runs. Case and spacing do **not** bust the key; **punctuation does**.
- The result is stored in **two tiers**: an in-memory LRU with a 2-hour TTL, checked *before* the SQLite `resolutions` table. A cache hit returns without re-writing, so reading a poisoned entry does not refresh it — but it also means deleting the SQLite row is not sufficient on its own.
- The same label can behave differently across word-level edits: `Urinary Antispasmodic - Anticholinergics, Non-Selective` failed; `Urinary Antispasmodics - …` (pluralised, fresh key) **succeeded**, `373293005` @ 0.60 in 35.8 s; `Urinary Antispasmodic - Anticholinergic, …` (fresh key) returned a **legitimate** no-match, `"Agentic eval matched 0 candidate(s) after 13 tool call(s)"`, in 58.7 s.

So the failure is partly but not wholly input-correlated, and once it occurs the answer is pinned regardless.

### Recovering a poisoned entry

Confirmed working, on a live instance:

```sql
-- resolutions(cache_key TEXT PRIMARY KEY, data TEXT, cached_at INTEGER)
DELETE FROM resolutions WHERE cache_key IN (…);   -- 8332 rows -> 8302
```

then **restart the service** to flush the in-memory tier. Deleting alone is not enough: immediately after a verified delete, the same query still returned the poisoned body in 0.045 s from memory. There is no documented cache-control flag or admin endpoint.

---

## 4. What it is not — controlled experiment

60 calls in three arms against the same service, same `url`, same `system`; the only variables were label shape and concurrency. Client timeout was 120 s.

| arm | labels | concurrency | n | min | median | p90 | max | **server failures** | client timeouts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ETC class names | **1** | 20 | 4.75 s | 32.10 s | 70.67 s | 118.53 s | **2** | 0 |
| 2 | ETC class names | 12 | 20 | 4.86 s | 14.92 s | 69.05 s | 120.02 s | **0** | 2 |
| 3 | GSN drug names | 12 | 20 | 0.11 s | 21.79 s | 93.35 s | 120.04 s | **0** | 2 |

The 120 s entries are the **client** giving up, not the bug. Only Arm 1 produced genuine `"No response from agentic evaluator"` responses.

### Not concurrency
Both genuine failures occurred at **concurrency 1**. The two 12-worker arms produced none. The reporter has previously run this service at **12 concurrent workers for extended periods with no failures at all**.

### Not a timeout
Failures returned at **68.2 s and 36.0 s**, while *successful* calls in the same arms ran to **70.7 s, 75.5 s, 93.3 s and 118.5 s**. A call can succeed at 118 s and fail at 36 s, so no wall-clock deadline explains the outcome. **Raising a timeout will not fix this.**

### Not label shape or length
Arm 3 is decisive. Identical trivial one-word drug names span three orders of magnitude:

```
Biotin           0.11 s   ok
tobramycin       0.80 s   ok
Thermotabs      93.35 s   ok
Gaviscon       120.04 s   client gave up
```

Long multi-clause class names and short single-word drug names both succeed quickly and both hang.

### Not input validity
Every failing label is ordinary clinical text. Several failing strings succeed after a one-word change, and the near-identical variant returns a sensible concept.

---

## 5. Server-log evidence

From `orchestration-new/logs/code-search.log` (4,616 lines). The log is a structured per-request metrics stream (`evt:"find_code"`, one JSON object per call) plus raw `[ontoserver]` / `[search-loop]` tool traces.

### The two failing calls, identified

The string `"No response from agentic evaluator"` **never appears in the log** — response bodies and `reasoning` text are not logged. The two rows below were matched to our failures by timestamp, latency *and* label text simultaneously (log is UTC; the experiment ran AEST, UTC+10):

```json
{"ts":"2026-08-10T11:22:36.402Z","text":"Immunomodulator B-Lymphocyte Stimulator (BLyS)-Specific Inhibitors MCAB",
 "result_code":null,"path":"agentic","rounds":10,"turns":5,"tool_calls":0,
 "latency_ms":68222,"completion_tokens":1192,"cost_usd":0.00168570666,"model":"deepseek/deepseek-v4-flash-0731"}

{"ts":"2026-08-10T11:33:28.629Z","text":"Contraceptives - Intravaginal, Systemic - Estrogen and Progestin Combs.",
 "result_code":null,"path":"agentic","rounds":13,"turns":5,"tool_calls":0,
 "latency_ms":35981,"completion_tokens":1339,"cost_usd":0.0010629709200000001,"model":"deepseek/deepseek-v4-flash-0731"}
```

`68222 ms` and `35981 ms` match the measured 68.23 s and 35.99 s; `11:22:36Z` and `11:33:28Z` are 21:22:36 and 21:33:28 AEST, matching Arm 1 calls 7 and 19.

### What the trace shows — and what it doesn't

The raw tool traces immediately preceding both calls show a **completely ordinary, error-free** multi-round search: `[ontoserver] $expand filter=… → N total, N returned`, `$translate → 0 matches (result=false)`, repeated synonym and broader-term retries, ending with no code.

Across the entire 4,616-line file there is **no stack trace, no HTTP 4xx/5xx from the LLM provider, no `429`, and no `timeout`, `abort`, `exception`, `retry`, `backoff` or JSON-parse-error**. (The only `422`s are unrelated, handled Ontoserver "invalid SNOMED concept ID" validations from a different flow.)

So the evaluator did not fail to respond. It responded across 10–13 rounds and the search concluded without a code.

| signature | count | note |
|---|---|---|
| `path:"agentic"`, `result_code:null`, no error | **39 / 135 agentic calls (29%)** | latency continuum 3.7–118.5 s, driven by `rounds` (3–13) and `completion_tokens` (148–2,682) |
| `path:"none"` + `validation_error` / `valueset_not_found` | 8 | unrelated malformed test requests, outside our experiment |
| any HTTP / provider / timeout / parse error | **0** | absent from the whole file |

One behaviour pattern, not several.

### Caching of null results — confirmed directly

The log demonstrates the mechanism unambiguously. For one text, an agentic null at 24.2 s is then replayed 10 times from cache at 1 ms:

```
ts=10:19:30.397Z "multivitamin with antioxidants, A, C,E"  path:"agentic"  result_code:null  latency_ms:24205
ts=10:20:01.730Z  (same text)                              path:"cached"  result_code:null  latency_ms:1  model:null  cost_usd:0
```

**293 rows** carry `path:"cached"` with `result_code:null`. The behaviour generalises beyond this bug: **any** null outcome is cached and replayed indefinitely.

### Incidental defect

`tool_calls` is **`0` on all 1,397 requests**, while the traces show thousands of real Ontoserver calls. The counter appears dead or miswired, and it hides how much tool-loop work preceded a null result.

---

## 6. Latency, separately from the bug

Even excluding failures, response time is extraordinarily variable for comparable inputs on a fixed constraint: **0.11 s to 118.53 s**. Arm 1 (strictly serial, one call at a time, no contention) went `22 s → 4.8 s → 21.6 s → 24 s → … → 118.5 s → … → 21.2 s`, with no trend and no relation to label length.

The log explains it: latency is `rounds × turns` inside a single request, each round issuing an LLM call plus one or more Ontoserver round-trips (3,174 Ontoserver lines across 1,397 requests). Rounds range 1–13; 3 rounds ≈ 4–10 s, 10–13 rounds ≈ 30–120 s. The sub-second cases are `path:"cached"` hits at `latency_ms:1`. There is **no internal retry** — each log line is one complete attempt.

So the variance is inherent to the agentic loop rather than a separate fault. It is still worth reporting, because a client cannot set a sensible timeout against a 0.1–118 s distribution: any value low enough to be useful will abandon calls that would have succeeded.

---

## 7. What we would ask for

Ordered by value to a caller.

1. **Do not cache the failure.** This is the single highest-value fix, and it is specifically the `"No response from agentic evaluator"` outcome that must not be cached — a legitimate no-match is a real answer and caching it is fine. Today one failure pins that input's answer across both tiers, so it cannot self-heal, and recovery needs a SQL delete *plus* a restart.
2. **Distinguish the two outcomes in the response**, machine-readably. A caller must treat them differently: a no-match is worth committing, a failure is worth retrying. Both currently arrive as HTTP 200 with `matches: []`, and the only discriminator is substring-matching undocumented free text — which silently breaks if the message is ever reworded. A distinct status code or an `outcome` enum would fix it.
3. **Say what actually failed.** `"No response from agentic evaluator"` is not accurate — the log shows 10–13 rounds and >1,000 completion tokens on the calls that produce it, so the evaluator plainly responded. Something naming the real condition (a final synthesis/parse step returning nothing?) would have replaced this entire investigation with a glance.
4. **Log the response body** (`matches`, `reasoning`) per request, not just `result_code`/`confidence`. This is the biggest diagnosability gap: a legitimate no-match and a genuine internal failure are currently indistinguishable *in the log as well as* in the response, which is why we had to identify the failing calls by latency-matching.
5. **Stop raw model markup leaking into `reasoning`.** 8 of 241 no-match rows in one run carried DeepSeek tool-call tokens verbatim, e.g. `<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name="search">…`, instead of prose. Harmless here, but it suggests an unparsed turn is being surfaced to callers.
6. **Instrument the step that converts "no structured answer" into a client response** — log the raw last-turn completion or a truncation/parse-failure flag, so a malformed LLM turn can be told from a deliberate conclusion.
7. **Fix the `tool_calls` counter**, which is `0` on all 1,397 requests despite thousands of real tool calls.
8. **Provide a way to clear or bypass the cache** — a cache-control flag on the request or an admin endpoint.
9. **For monitoring**, emit a distinct log line where the message is actually generated, e.g. `evt:"agentic_empty_result", request_id, rounds, last_turn_len`. That one line would have made this a `grep` instead of a latency-matching exercise.

---

## 8. Environment

| | |
|---|---|
| code-search | recently updated; exact version unknown (`/health` reports `{"status":"ok","version":"dev"}`) |
| LLM provider/model | `deepseek/deepseek-v4-flash-0731` (135/135 agentic calls) |
| endpoint | `POST /api/v1/find-code`; only `/api/v1/find-code`, `/api/v1/feedback`, `/health`, `/docs` observed |
| terminology server | Ontoserver at `https://velonto.dw.csiro.au/fhir`, self-signed cert |
| SNOMED CT | AU edition only, versions `20260430` and `20250731`; module `32506021000036107` |
| constraint | `http://snomed.info/sct?fhir_vs=ecl/<<105590001` — 29,670 concepts |
| request params | `max_candidates: 1`, `effort: "balanced"` |
| observed | 2026-08-10, ~14:00–21:40 local |

**Prior workloads that never showed this:** the same service, same Ontoserver, against RxNorm (VCL constraint, 73,214 codes) and against SNOMED ECL constraints for procedures, specimens and lab observations — thousands of calls at up to 12 concurrent workers.

---

## 9. Appendix — Arm 3 inputs verbatim

Real `mimic-medication-gsn` displays, sent unmodified, at concurrency 12:

```
  0.11s ok  Biotin                          28.37s ok  Probiotic Blend
  0.62s ok  sodium hypochlorite             28.92s ok  multivit, min no.20-iron-folic
  0.77s ok  meclofenamate                   30.80s ok  doxercalciferol [Hectorol]
  0.80s ok  tobramycin                      44.95s ok  PNV combo #22-iron-FA-om3-dha [Prefera-OB Plus DHA]
  0.81s ok  oxacillin                       58.76s ok  benzocaine-pectin [Cepacol Sore Throat + Coating]
  0.90s ok  diethylpropion                  93.35s ok  Thermotabs
  0.95s ok  ketorolac                      120.04s -- Gammagard S-D (IgA < 1 mcg/mL)   (client gave up)
  1.03s ok  Isoniazid                      120.04s -- Gaviscon                          (client gave up)
  7.74s ok  Tessalon
 16.67s ok  salicyl acd-sulfur (keratol)
 26.91s ok  milrinone in D5W
 26.91s ok  iloperidone [Fanapt]
```

Arm 1 and Arm 2 used ETC class names mutated by one word each, to obtain fresh cache keys while preserving length and clause structure.

---
