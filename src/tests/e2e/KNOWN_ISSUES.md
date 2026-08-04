# Known browser issues

## PDF.js ESM default export

Every application shell currently imports `https://cdn.jsdelivr.net/npm/pdfjs-dist@4.7.76/+esm` as a default export. That module does not provide a `default` export, so Chromium raises a page error on every route even when the page otherwise renders correctly.

The problem page then also logs `pdfjsLib is not defined` when its fragment
initialization tries to use the unavailable global.

The E2E runtime diagnostics allowlist only the stable
`pdfjs-dist@4.7.76/+esm` and `pdfjsLib is not defined` fragments from this
known error by default. Page errors, console errors, and failed
document/script/XHR/fetch requests continue to fail tests. Remove both default
allowlist entries from `node/src/fixtures.ts` when the application import is
corrected.

Additional temporary exceptions can be supplied with `NTOJ_E2E_ALLOWED_BROWSER_ERRORS`; separate multiple text fragments with `||`.


## Same-second session collision

Session IDs are currently generated with `create_signed_value("id", acct_id)`. Two logins for the same account within the same one-second timestamp window can therefore produce the same signed value and overwrite the same `account_session@{acct_id}` Redis hash entry. The account page then reports one device even though two browser contexts signed in.

The remote-logout E2E test waits across that timestamp boundary so it can exercise two distinct sessions. Remove the delay after session IDs include per-login uniqueness.


## Contest description script closing sequence

Contest descriptions are embedded into an inline JavaScript template literal after escaping only backslashes and backticks. A literal `</script>` in otherwise valid Markdown therefore terminates the surrounding script element and leaves the rendered description blank.

The description E2E test still verifies DOMPurify event-handler sanitization with an `onerror` attribute. Add safe script-element escaping to `markdown_escape` before covering literal `</script>` as a passing render case.

## Judge signal classification

The current external Judge Rewrite image treats a deterministic `SIGSEGV` as a
normal execution and lets the checker turn it into WA. The system spec and
legacy integrated test require RESIG. The Playwright case remains an expected
failure; see [`JUDGE_SPEC_DIFFERENCES.md`](JUDGE_SPEC_DIFFERENCES.md) for the
reproduction and Judge log evidence.
