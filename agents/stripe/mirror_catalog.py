#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["stripe>=11"]
# ///
"""
mirror_catalog.py — recreate a LIVE Stripe catalog (Products + Prices) in TEST mode.

Stripe objects do NOT cross test↔live, so a live price-id is useless to a test key. To homologate
a production app you must rebuild its catalog in test mode. This does that idempotently: each
mirrored object carries `metadata.mirror_source = <live_id>`, so re-runs skip what already exists
instead of duplicating. It then prints a `code → test_price_id` map and an env block you paste into
the app's TEST profile (e.g. STRIPE_PRICE_ID_PADRAO=price_test_...).

Keys:
  --live-key  a LIVE *restricted, READ-ONLY* key (rk_live_…) — reads the live catalog only.
              Never pass a live secret key; this script only ever READS with it.
  --test-key  a TEST secret key (sk_test_… / rk_test_… with write) — creates the test objects.

Usage:
  uv run agents/stripe/mirror_catalog.py --live-key rk_live_xxx --test-key sk_test_xxx
  uv run agents/stripe/mirror_catalog.py --live-key rk_live_xxx --test-key sk_test_xxx --write-env homolog.env
  uv run agents/stripe/mirror_catalog.py --test-key sk_test_xxx --from-json catalog.json   # author from a file

The `code` for each price is, in order of preference: its `lookup_key`, else the product name
slugified, else the price id — so the env var names are stable across runs.
"""
import argparse
import json
import re
import sys

import stripe

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "item"


def code_for(price: dict, product_name: str) -> str:
    return price.get("lookup_key") or slug(product_name) or price["id"]


def fetch_live(client: "stripe.StripeClient") -> list[dict]:
    """Return [{product, prices:[...]}] for all active live products with active prices."""
    out: dict[str, dict] = {}
    for prod in client.products.list({"active": True, "limit": 100}).auto_paging_iter():
        out[prod["id"]] = {"product": prod, "prices": []}
    for price in client.prices.list({"active": True, "limit": 100, "expand": ["data.product"]}).auto_paging_iter():
        prod = price.get("product")
        pid = prod["id"] if isinstance(prod, dict) else prod
        if pid in out:
            out[pid]["prices"].append(price)
    return [v for v in out.values() if v["prices"]]


def find_test_product(client: "stripe.StripeClient", live_id: str) -> dict | None:
    res = client.products.search({"query": f"metadata['mirror_source']:'{live_id}'", "limit": 1})
    data = res.get("data", [])
    return data[0] if data else None


def find_test_price(client: "stripe.StripeClient", live_id: str) -> dict | None:
    res = client.prices.search({"query": f"metadata['mirror_source']:'{live_id}'", "limit": 1})
    data = res.get("data", [])
    return data[0] if data else None


def mirror_price(client, live_price: dict, test_product_id: str) -> dict:
    existing = find_test_price(client, live_price["id"])
    if existing:
        return existing
    params: dict = {
        "product": test_product_id,
        "currency": live_price["currency"],
        "metadata": {"mirror_source": live_price["id"], **(live_price.get("metadata") or {})},
    }
    if live_price.get("nickname"):
        params["nickname"] = live_price["nickname"]
    if live_price.get("lookup_key"):
        params["lookup_key"] = live_price["lookup_key"]
        params["transfer_lookup_key"] = False
    if live_price.get("unit_amount") is not None:
        params["unit_amount"] = live_price["unit_amount"]
    if live_price.get("recurring"):
        r = live_price["recurring"]
        params["recurring"] = {k: r[k] for k in ("interval", "interval_count", "usage_type") if r.get(k) is not None}
    if live_price.get("tax_behavior") and live_price["tax_behavior"] != "unspecified":
        params["tax_behavior"] = live_price["tax_behavior"]
    return client.prices.create(params)


def mirror_product(client, live_product: dict) -> dict:
    existing = find_test_product(client, live_product["id"])
    if existing:
        return existing
    params = {
        "name": live_product["name"],
        "active": True,
        "metadata": {"mirror_source": live_product["id"], **(live_product.get("metadata") or {})},
    }
    if live_product.get("description"):
        params["description"] = live_product["description"]
    return client.products.create(params)


def author_from_json(client, spec: list[dict]) -> list[tuple[str, dict]]:
    """spec: [{name, description?, prices:[{code?, currency, unit_amount, recurring?}]}] → [(code, test_price)]."""
    pairs = []
    for item in spec:
        prod = client.products.create({"name": item["name"], "active": True,
                                       **({"description": item["description"]} if item.get("description") else {})})
        for pr in item["prices"]:
            params = {"product": prod["id"], "currency": pr["currency"], "unit_amount": pr["unit_amount"]}
            if pr.get("recurring"):
                params["recurring"] = pr["recurring"]
            if pr.get("lookup_key"):
                params["lookup_key"] = pr["lookup_key"]
            price = client.prices.create(params)
            pairs.append((pr.get("code") or code_for(price, item["name"]), price))
    return pairs


def main() -> int:
    p = argparse.ArgumentParser(description="Mirror a live Stripe catalog into test mode (idempotent).")
    p.add_argument("--test-key", required=True, help="TEST secret key (sk_test_/rk_test_ with write)")
    p.add_argument("--live-key", help="LIVE read-only restricted key (rk_live_) — reads live catalog")
    p.add_argument("--from-json", help="author the catalog from a JSON spec file instead of mirroring live")
    p.add_argument("--write-env", help="also write the env block to this file")
    args = p.parse_args()

    if args.test_key.startswith(("sk_live_", "rk_live_")):
        print("REFUSE: --test-key is a LIVE key. Pass a sk_test_/rk_test_ key.", file=sys.stderr)
        return 2
    test = stripe.StripeClient(args.test_key)

    pairs: list[tuple[str, dict]] = []
    if args.from_json:
        spec = json.load(open(args.from_json, encoding="utf-8"))
        pairs = author_from_json(test, spec)
    else:
        if not args.live_key:
            print("Provide --live-key (rk_live_ read-only) or --from-json.", file=sys.stderr)
            return 2
        if not args.live_key.startswith("rk_live_"):
            print("WARN: --live-key is not an rk_live_ restricted key. Use a READ-ONLY restricted "
                  "live key so this can only read.", file=sys.stderr)
        live = stripe.StripeClient(args.live_key)
        for entry in fetch_live(live):
            tp = mirror_product(test, entry["product"])
            for lp in entry["prices"]:
                price = mirror_price(test, lp, tp["id"])
                pairs.append((code_for(lp, entry["product"]["name"]), price))

    # Report
    print("\n# code → test price id")
    env_lines = []
    for code, price in pairs:
        amount = price.get("unit_amount")
        cur = price.get("currency", "").upper()
        rec = price.get("recurring")
        kind = f"{rec['interval']}ly" if rec else "one-time"
        money = f"{amount/100:.2f} {cur}" if amount is not None else "metered/free"
        print(f"  {code:<28} {price['id']:<32} {money:<14} {kind}")
        env_lines.append(f"STRIPE_PRICE_ID_{code.upper()}={price['id']}")

    print("\n# env block (paste into the app's TEST profile)")
    block = "\n".join(env_lines)
    print(block)
    if args.write_env:
        with open(args.write_env, "w", encoding="utf-8") as f:
            f.write(block + "\n")
        print(f"\nwrote {args.write_env}")
    print(f"\n{len(pairs)} price(s) mirrored/authored in TEST mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
