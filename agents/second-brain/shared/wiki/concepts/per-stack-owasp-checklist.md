---
title: Per-stack OWASP detection checklist (ripgrep patterns)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, owasp, ripgrep, checklist, shared]
---

# Per-stack OWASP detection checklist (ripgrep patterns)

High-signal `rg` grep patterns to triage a codebase fast, grouped by stack — each line is a first
pass that flags a likely [[owasp-top-10-2021-mapping|OWASP]] issue for human confirmation, not a
proof. A hit is a lead; a miss is not a clean bill (use [[two-layer-security-review]] for depth).

## Cross-stack (any language)
- **CORS `*` + credentials** (A05): `rg -n "allowCredentials\(true\)|Access-Control-Allow-Credentials" ` together with an origin of `*`.
- **SSRF → cloud metadata** (A10): `rg -n "169\.254\.169\.254|metadata\.google|/latest/meta-data"`.
- **Committed key material** (A02): `rg --files | rg "\.(p12|pem|key|jks|pfx|p8)$"` plus `serviceAccount.*\.json`.
- **Hardcoded secrets** (A02): `rg -n "(sk_live|AKIA|AIza|ghp_|xox[baprs]-|-----BEGIN .*PRIVATE KEY)"`.

## Spring Boot (Java/Kotlin)
- SQL concat (A03): `rg -n "createQuery\(.*\"\s*\+|\"\s*\+\s*\w+\s*\+\s*\""`; flag string-built JPQL/SQL vs `?`/named params.
- Command injection (A03): `rg -n "Runtime\.getRuntime\(\)\.exec|ProcessBuilder"`.
- **Actuator / Swagger exposed** (A05): `rg -n "management\.endpoints\.web\.exposure\.include|springdoc|swagger-ui"` — confirm not `permitAll` in prod.
- Permit-all + missing webhook verify (A08): `rg -n "permitAll|antMatchers.*permitAll"` then check those endpoints sign-verify (see [[webhook-signature-verification]]).

## FastAPI / Python
- `rg -n "verify=False"` (A02 — TLS off) · `rg -n "shell=True"` (A03) · `rg -n "yaml\.load\(|pickle\.loads\(|eval\(|exec\("` (A03/A08).
- Disabled auth/JWT (A07): `rg -n "verify_signature.*False|options=\{.*verify"`; `rg -n "algorithms=\[.*none"`.

## React + Vite
- XSS (A03): `rg -n "dangerouslySetInnerHTML"`.
- **Client-bundle secret leak** (A02): `rg -n "import\.meta\.env\.VITE_|VITE_.*KEY|VITE_.*SECRET"` — see [[client-bundle-secret-leakage]].
- Token storage (A07): `rg -n "localStorage\.setItem.*token|sessionStorage.*token"`.

## Next.js
- **CVE-2025-29927 middleware bypass** (A01): vulnerable when `next` < 14.2.25 (14.x) / < 15.2.3 (15.x) / < 13.5.9 / < 12.3.5, with auth in `middleware.ts`. A spoofed `x-middleware-subrequest` header skips middleware entirely. `rg -n "\"next\":" package.json` to check the pin; `rg -n "x-middleware-subrequest"`. Fix: upgrade, or have the proxy strip the header.
- Server secret leak (A02): `rg -n "NEXT_PUBLIC_"` — anything `NEXT_PUBLIC_*` ships to the browser ([[client-bundle-secret-leakage]]).

## React Native / Expo
- Plaintext storage (A02): `rg -n "AsyncStorage\.setItem"` for tokens/PII (use SecureStore/Keychain instead).
- `rg -n "EXPO_PUBLIC_"` — inlined into the JS bundle and APK ([[client-bundle-secret-leakage]]).

## Node / Express
- Command injection (A03): `rg -n "child_process|exec\(|execSync\("`.
- SQL concat (A03): `rg -n "query\(\s*[\`\"'].*\$\{|\"\s*\+\s*req\."`.
- Missing webhook verify (A08): `rg -n "express\.raw|bodyParser\.raw"` near a webhook route, then confirm a signature check.

## JavaFX / desktop
- Command injection (A03): `rg -n "Runtime\.getRuntime|ProcessBuilder"`.
- Secrets in code/resources (A02): `rg -n "password\s*=|apiKey\s*="` across `src/main/resources`.

Related: [[owasp-top-10-2021-mapping]] · [[client-bundle-secret-leakage]] · [[webhook-signature-verification]] · [[two-layer-security-review]]
