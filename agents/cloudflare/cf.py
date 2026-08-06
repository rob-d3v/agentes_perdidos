#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.34"]
# ///
"""
cloudflare agent — read-safe Cloudflare account tool.

Reads creds from the repo .env (walked up from CWD). NEVER prints token/key VALUES.

Subcommands:
  verify                       account-owned token verify (/accounts/{id}/tokens/verify)
  inventory                    full read-only fleet map (zones, R2 buckets+CORS, workers, pages, turnstile)
  buckets                      list R2 buckets
  cors-get   <bucket>          print current CORS ruleset (ALWAYS run before editing)
  cors-put   <bucket> <file>   REPLACE CORS with rules from a JSON file ({"rules":[...]}). Prints a
                               diff-ish before/after and requires --yes. GET+merge is on YOU — this
                               PUTs exactly what's in the file (the API replaces the whole ruleset).
  presign    <bucket> <key>    print a presigned PUT + GET url (S3 keys). --expires N (default 3600),
                               --content-type TYPE
  dns-list   <zone_id>         list DNS records for a zone
  purge      <zone_id>         purge cache. --everything OR --files url1,url2
  turnstile-list               list Turnstile widgets (sitekeys are public)

Auth model: TOKEN_API_CLOUDFRARE is an ACCOUNT-OWNED token → verify at /accounts/{id}/tokens/verify,
NOT /user/tokens/verify (that returns "Invalid API Token" 1000 for account tokens).
"""
import argparse, json, os, sys, urllib.request, urllib.error
from pathlib import Path

BASE = "https://api.cloudflare.com/client/v4"


def find_env():
    d = Path.cwd()
    for cand in [d, *d.parents]:
        f = cand / ".env"
        if f.exists():
            return f
    raise SystemExit("no .env found walking up from CWD")


def load_env():
    env = {}
    for line in find_env().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.split("#")[0].strip().strip('"').strip("'")
    return env


ENV = load_env()
ACCOUNT = ENV.get("ACCOUNT_ID_CLOUDFLARE", "")
TOKEN = ENV.get("TOKEN_API_CLOUDFRARE", "")


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"success": False, "http_status": e.code}
    except Exception as e:
        return {"success": False, "errors": [str(e)]}


def ok(r):
    return isinstance(r, dict) and r.get("success")


def dump(x):
    print(json.dumps(x, indent=2, ensure_ascii=False))


def cmd_verify(a):
    r = api("GET", f"/accounts/{ACCOUNT}/tokens/verify")
    dump({"success": r.get("success"), "status": (r.get("result") or {}).get("status"), "errors": r.get("errors")})
    sys.exit(0 if ok(r) and (r.get("result") or {}).get("status") == "active" else 1)


def cmd_buckets(a):
    r = api("GET", f"/accounts/{ACCOUNT}/r2/buckets")
    res = r.get("result")
    buckets = res.get("buckets") if isinstance(res, dict) else res
    dump([{"name": b.get("name"), "creation_date": b.get("creation_date")} for b in (buckets or [])] if ok(r) else r.get("errors"))


def cmd_inventory(a):
    out = {}
    acc = api("GET", f"/accounts/{ACCOUNT}")
    out["account"] = {"id_last4": ACCOUNT[-4:], "name": (acc.get("result") or {}).get("name")}
    v = api("GET", f"/accounts/{ACCOUNT}/tokens/verify")
    out["token_status"] = (v.get("result") or {}).get("status") if ok(v) else v.get("errors")
    z = api("GET", f"/zones?account.id={ACCOUNT}&per_page=50")
    out["zones"] = [{"name": r.get("name"), "id": r.get("id"), "status": r.get("status")} for r in (z.get("result") or [])] if ok(z) else z.get("errors")
    b = api("GET", f"/accounts/{ACCOUNT}/r2/buckets")
    res = b.get("result")
    buckets = res.get("buckets") if isinstance(res, dict) else res
    out["r2_buckets"] = []
    for bk in (buckets or []):
        name = bk.get("name")
        c = api("GET", f"/accounts/{ACCOUNT}/r2/buckets/{name}/cors")
        out["r2_buckets"].append({
            "name": name,
            "creation_date": bk.get("creation_date"),
            "cors_rule_count": len((c.get("result") or {}).get("rules", [])) if ok(c) else "none/err",
        })
    w = api("GET", f"/accounts/{ACCOUNT}/workers/scripts")
    out["workers"] = [x.get("id") for x in (w.get("result") or [])] if ok(w) else w.get("errors")
    p = api("GET", f"/accounts/{ACCOUNT}/pages/projects")
    out["pages"] = [x.get("name") for x in (p.get("result") or [])] if ok(p) else p.get("errors")
    t = api("GET", f"/accounts/{ACCOUNT}/challenges/widgets")
    out["turnstile"] = [{"name": x.get("name"), "sitekey": x.get("sitekey"), "domains": x.get("domains")} for x in (t.get("result") or [])] if ok(t) else t.get("errors")
    dump(out)


def cmd_cors_get(a):
    r = api("GET", f"/accounts/{ACCOUNT}/r2/buckets/{a.bucket}/cors")
    dump(r.get("result") if ok(r) else r.get("errors"))


def cmd_cors_put(a):
    cur = api("GET", f"/accounts/{ACCOUNT}/r2/buckets/{a.bucket}/cors")
    new = json.loads(Path(a.file).read_text(encoding="utf-8"))
    print("=== CURRENT (will be REPLACED) ===")
    dump(cur.get("result") if ok(cur) else cur.get("errors"))
    print(f"=== NEW ({len(new.get('rules', []))} rules) ===")
    dump(new)
    if not a.yes:
        print("\nRefusing to PUT without --yes. PUT replaces the ENTIRE ruleset — confirm the merge is correct.")
        sys.exit(2)
    r = api("PUT", f"/accounts/{ACCOUNT}/r2/buckets/{a.bucket}/cors", new)
    dump({"success": r.get("success"), "errors": r.get("errors")})
    sys.exit(0 if ok(r) else 1)


def cmd_presign(a):
    import boto3
    ep = ENV.get("S3_API_ENDPOINT_CLOUDFLARE") or f"https://{ACCOUNT}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3", endpoint_url=ep,
        aws_access_key_id=ENV.get("ACCESS_KEY_CLOUDFLARE"),
        aws_secret_access_key=ENV.get("SECRET_ACCESS_KEY_CLOUDFLARE"),
        region_name="auto",
    )
    put_params = {"Bucket": a.bucket, "Key": a.key}
    if a.content_type:
        put_params["ContentType"] = a.content_type
    put_url = s3.generate_presigned_url("put_object", Params=put_params, ExpiresIn=a.expires)
    get_url = s3.generate_presigned_url("get_object", Params={"Bucket": a.bucket, "Key": a.key}, ExpiresIn=a.expires)
    dump({"put_url": put_url, "get_url": get_url, "expires_in": a.expires,
          "note": "browser PUT also needs bucket CORS: method PUT + exposeHeaders ETag"})


def cmd_dns_list(a):
    r = api("GET", f"/zones/{a.zone_id}/dns_records?per_page=100")
    dump([{"type": x.get("type"), "name": x.get("name"), "content": x.get("content"),
           "proxied": x.get("proxied"), "id": x.get("id")} for x in (r.get("result") or [])] if ok(r) else r.get("errors"))


def cmd_purge(a):
    if a.everything:
        body = {"purge_everything": True}
    elif a.files:
        body = {"files": [u.strip() for u in a.files.split(",") if u.strip()]}
    else:
        raise SystemExit("purge: pass --everything or --files url1,url2")
    r = api("POST", f"/zones/{a.zone_id}/purge_cache", body)
    dump({"success": r.get("success"), "errors": r.get("errors")})
    sys.exit(0 if ok(r) else 1)


def cmd_turnstile_list(a):
    r = api("GET", f"/accounts/{ACCOUNT}/challenges/widgets")
    dump([{"name": x.get("name"), "sitekey": x.get("sitekey"), "mode": x.get("mode"),
           "domains": x.get("domains")} for x in (r.get("result") or [])] if ok(r) else r.get("errors"))


def main():
    p = argparse.ArgumentParser(description="read-safe Cloudflare account tool")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("inventory").set_defaults(fn=cmd_inventory)
    sub.add_parser("buckets").set_defaults(fn=cmd_buckets)
    sub.add_parser("turnstile-list").set_defaults(fn=cmd_turnstile_list)
    g = sub.add_parser("cors-get"); g.add_argument("bucket"); g.set_defaults(fn=cmd_cors_get)
    g = sub.add_parser("cors-put"); g.add_argument("bucket"); g.add_argument("file"); g.add_argument("--yes", action="store_true"); g.set_defaults(fn=cmd_cors_put)
    g = sub.add_parser("presign"); g.add_argument("bucket"); g.add_argument("key"); g.add_argument("--expires", type=int, default=3600); g.add_argument("--content-type", default=None); g.set_defaults(fn=cmd_presign)
    g = sub.add_parser("dns-list"); g.add_argument("zone_id"); g.set_defaults(fn=cmd_dns_list)
    g = sub.add_parser("purge"); g.add_argument("zone_id"); g.add_argument("--everything", action="store_true"); g.add_argument("--files", default=None); g.set_defaults(fn=cmd_purge)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
