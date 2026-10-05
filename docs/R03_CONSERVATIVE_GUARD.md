# R03 conservative candidate — scoped local-fallback contract

## Boundary

This sparse candidate starts from the immutable 313-file `merged-v1` source,
fingerprint `1d5f9fd24d8e12c26fb2b63d33b6fa7aeba9a288db664893d42018e15b27f2fa`.
The starting guard raw SHA256 is
`a9d5016ef31468121f4a265dc927ab25653c4469036117208c6451a9f68c357e`.
The previously rejected candidate is not the baseline and must remain unchanged.

All eleven original regexes, public signatures, social closer and batch contract
remain intact. Default rejection is preserved for every matching input unless
its **complete field** is one narrowly recognized descriptive sentence. There
is no finite list of attack/action verbs whose absence grants admission.

## Positive grammar

The only exempted matches are the bare terms `jailbreak`, `prompt injection`,
`prompt hack`, and `prompt leak`, in these closed sentence families:

- A documentation/report/article/audit/glossary/lesson subject describes,
  discusses, lists or reviews a term's risks, prevention, defenses or terminology.
- The same subject defines or describes a term as a security threat or a threat
  to data/trust boundaries.
- We/researchers/the authors/Dan and Jordan discussed, studied or reviewed a
  term's risks/prevention/defenses, or defenses against the term.
- A report/article/glossary/lesson quoted **the term alone** inside double quotes,
  followed by `without issuing an instruction`.
- `The words '<term>' name a security threat.`
- `Atlas notes describe <term> defenses.`

Each admitted sentence has exactly one term slot, a required final full stop,
fixed subject/predicate/object vocabulary, and no arbitrary prose slot. The
quoted-term family does not trust a self-declared `not an instruction`: its
quoted contents can only be the bare term, not a payload. Extra prefix/suffix,
newlines, multiple term matches, commands and classifier/benign claims do not
fit the grammar. Unsupported harmless phrasing can remain blocked intentionally.
All other matches (including DAN/system-prompt/role alternatives in the same
original regex) are rejected on both the raw input and diagnostic projection.
All scanning and the positive grammar run before display truncation.

## Diagnostic Unicode projection

The second bounded TDD slice adds NFKC + casefold and a finite Cyrillic-lookalike
map for а/с/е/і/ј/о/р/ѕ/у/х. It removes only soft hyphen, zero-width space,
zero-width nonjoiner/joiner, word joiner and BOM. This is detection-only; admitted
source text and its truncation use the original bytes/code points. A complete
projected descriptive sentence can admit an obfuscated bare term, but no raw or
projected nonterm pattern receives an exemption. No universal Unicode or
multilingual injection claim is made.

## Verification and limitations

The owner-approved runner preloads the whole real package and native SDK/
`MemoryProvider`; no provider stubs, extracted production functions or substitute
core are used. Seven genuine local-fallback seams are tested: sanitizer,
provider inspection, unified recall guard, model-safe row, document guard,
shared claim output and batch sanitizer. Tests construct real provider objects
without initialize, DB, live home, network or model requests.

The immutable supplied corpus contains **29 cases**, despite a context reference
to 31; its SHA is preserved and no invented cases fill that discrepancy.
R03-01..03 are descriptive positives. R03-04 quoted direct-command stays blocked.
All 16 A/O controls and the three previously rejected differential directives
remain rejection requirements. G01..03 are finite Unicode detection requirements.
G04 Russian directive and G05 raw role/context terminator remain separate known
limits, not closed vulnerabilities. No strict/shared-core/LLM/full-suite/lifecycle
acceptance, merge, deployment, push or live security/configuration change follows
from these receipts. Fresh independent review by the parent is still required.

## Evidence

`evidence/guard-r03-conservative/final-report.json` under the artifact root records
actual outcomes, production edit count (maximum two), failed RED gates, source
maps before/after, original and effective union fingerprints, native identities,
commands, JUnit errors separately from failures, and raw artifact hashes. Old
receipts' coordination fingerprint `48cfe...` is provenance only, never the
fingerprint of this current candidate union.


## Subsequent local G04/G05 derivative (bounded verification)

The preceding evidence and known-limit statements describe the historical R03
baseline; its receipts and corpus are preserved unchanged. The current derivative
adds rejection for the finite Russian override form and source-controlled
`memory-context` / `im_start` / `im_end` protocol markers, before truncation.
Cyrillic is scanned on raw and NFKC-casefold text before the Latin-lookalike
projection. All eleven original deny patterns and the closed descriptive-term
exception remain unchanged; admitted source is not rewritten.

The same ten stdlib regression tests recorded 8 PASS / 2 FAIL on the baseline
and 10 PASS on the derivative (no errors/skips). These are local-guard unit
receipts, not native downstream, strict/shared-trust, FULL or runtime acceptance.
They do not establish universal Russian, Unicode or semantic injection protection.
A new exact-source review, package proof and applicable native release gates are
required; the old baseline wheel does not verify the changed guard.
