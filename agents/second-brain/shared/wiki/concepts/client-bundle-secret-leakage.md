---
title: Client-bundle secret leakage (VITE_/NEXT_PUBLIC_/EXPO_PUBLIC_)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, secrets, frontend, a02, shared]
---

# Client-bundle secret leakage (VITE_/NEXT_PUBLIC_/EXPO_PUBLIC_)

Any env var with a public prefix — `VITE_*`, `NEXT_PUBLIC_*`, `EXPO_PUBLIC_*` — is **inlined as a
string literal into the shipped JS bundle at build time** and downloaded by every client, so a
private secret behind one of these prefixes is effectively published to the world. This is the most
common real-world [[owasp-top-10-2021-mapping|A02 Cryptographic Failures]] leak in SPA/mobile repos.

## Why it happens
Bundlers do **static text substitution**: Vite replaces `import.meta.env.VITE_X`, Next replaces
`process.env.NEXT_PUBLIC_X`, Expo replaces `process.env.EXPO_PUBLIC_X` — with the literal value, at
build. There is no runtime fetch, no server boundary. The value lives in `dist/assets/*.js`,
`.next/static/`, or the APK's `index.android.bundle`, in plaintext, forever in that build artifact.
The prefix is a **publish marker**, not a protection.

## What belongs client-side (publishable only)
Only **publishable / public** identifiers: Stripe `pk_live_…` (publishable, designed to be public),
Firebase web config / API key (a project identifier, secured by Firebase Security Rules + allowed
domains, not a secret), a public reCAPTCHA/Turnstile **site** key, a public Mapbox/Maps token with
domain referrer restriction.

## What must NEVER be client-side
Stripe `sk_live_…`, any service-account JSON, DB URLs, JWT signing keys, webhook signing secrets,
provider API secrets (SendGrid/Resend/Twilio), OAuth client *secrets*. These belong on a server; the
client calls your backend, the backend holds the secret.

## The required scan (artifact, not just source)
Scanning source is not enough — scan the **built output**, because that's what ships:
```bash
npm run build
gitleaks detect --no-git --source dist        # Vite
gitleaks detect --no-git --source .next/static # Next.js
# Expo/RN: build the APK, unzip, scan the extracted assets/ bundle
```
A secret found in `dist/` is **already burned** the moment any build was shipped — follow
[[secret-remediation-reversibility]] (rotate first). See [[scanner-stack]] for tooling.

Related: [[secret-remediation-reversibility]] · [[per-stack-owasp-checklist]] · [[owasp-top-10-2021-mapping]] · [[scanner-stack]]
