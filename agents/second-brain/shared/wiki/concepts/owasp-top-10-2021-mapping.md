---
title: OWASP Top 10 (2021) — finding mapping target
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, owasp, taxonomy, shared]
---

# OWASP Top 10 (2021) — finding mapping target

The OWASP Top 10 2021 categories (A01–A10) are the canonical taxonomy every security finding maps
to — give each finding an `Axx` tag so reviews are comparable across reviewers and stacks. This is
the 2021 edition (still current as the stable reference; a 2025 refresh is in draft). One line each
plus what it looks like in real code.

- **A01 — Broken Access Control** (#1 risk). Acting outside intended permissions: IDOR (`GET /api/orders/{id}` with no owner check), missing `@PreAuthorize`/route guard, force-browsing to admin routes, CORS that trusts any origin. *Code smell:* an authenticated endpoint that never re-checks the resource belongs to the caller.
- **A02 — Cryptographic Failures.** Sensitive data exposed by weak/absent crypto: plaintext or MD5/SHA1 password hashes (vs bcrypt/argon2), hardcoded keys, TLS disabled/`verify=False`, secrets in logs, PII unencrypted at rest.
- **A03 — Injection** (incl. XSS). Untrusted input reaches an interpreter: SQL string-concat, OS command via `shell=True`/`Runtime.exec`, LDAP/NoSQL/template injection, `dangerouslySetInnerHTML` / `innerHTML` with user data. *Fix:* parameterize / escape at the sink.
- **A04 — Insecure Design.** A flaw in the design itself, not the implementation: no rate limit on OTP, password reset that leaks account existence, business logic that trusts a client-supplied price. Threat-model fix, not a one-line patch.
- **A05 — Security Misconfiguration.** Insecure defaults / over-exposure: Spring Actuator or Swagger public, debug/stack traces in prod, default creds, directory listing, permissive S3 bucket, missing security headers.
- **A06 — Vulnerable & Outdated Components.** A known-CVE dependency or runtime: an old `log4j`/`lodash`/transitive package, unpatched base image. See [[dependency-supply-chain-security]].
- **A07 — Identification & Authentication Failures.** Weak auth: credential stuffing allowed (no lockout), session fixation, JWT with `alg:none` or unverified signature, weak/guessable tokens, MFA bypass.
- **A08 — Software & Data Integrity Failures.** Trusting unverified code/data: unsigned auto-update, insecure deserialization, CI pulling an unpinned action, **unverified webhook payloads** (see [[webhook-signature-verification]]). Supply-chain adjacent.
- **A09 — Security Logging & Monitoring Failures.** Can't detect/respond: auth failures not logged, no alerting, logs that leak secrets, no tamper-resistant audit trail. The gap that makes [[rfc-3227-ir-state-machine|incident response]] blind.
- **A10 — Server-Side Request Forgery (SSRF).** Server fetches an attacker-controlled URL: image-proxy / webhook-tester / PDF-renderer that will hit `http://169.254.169.254/` (cloud metadata) or internal services. *Fix:* allowlist + block link-local/private ranges.

Used by [[two-layer-security-review]] and the [[per-stack-owasp-checklist]] — the per-stack patterns
are grouped by the Axx they evidence.

Related: [[per-stack-owasp-checklist]] · [[two-layer-security-review]] · [[security-infra-brain]]
