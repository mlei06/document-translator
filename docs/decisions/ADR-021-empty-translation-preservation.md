# ADR-021 - Preserve Source Text for Empty Model Answers

Status: Accepted as the owner's requested fix, 2026-09-29. Amends the document pipeline's fail-whole-document behavior for an empty returned translation.

## Evidence

The user's SMALL-100 Greedy PDF job failed because the model returned an empty string for the company name 联想. Replaying the same document reproduced the failure. Beam 4 returned a nonempty but incorrect translation, so changing decoding is not a reliable correction.

## Decision

When an engine returns a blank/whitespace-only answer for a nonempty document text input, preserve that encoded source input and continue translating other inputs. Apply the same guard to formatting recovery calls. Keep protected and formatting markers intact. Do not silently switch models, hardcode a company-name dictionary, or claim that retained source text was translated.

Record `empty_translation_preserved` as a warning diagnostic with a count of preserved engine inputs. Show one document-level notice in the completed result's preview; download remains available. This is a translation warning, independent of layout checks. Engine exceptions, invalid response cardinality, corrupt files and failed saved-output verification still fail explicitly.

Bump the pipeline output strategy fingerprint so previously generated outputs are not reused under the new behavior. Existing jobs keep their immutable results. New saved results may be reused with their warning intact under the existing ownership/fingerprint rules.

## Verification

Regression tests verify that a blank answer preserves the source while valid sibling translations are applied and originals remain unchanged. Replay the reported PDF with the actual SMALL-100 preset and verify the output and warning. The browser notice must not disable downloads or introduce per-area layout warnings.
