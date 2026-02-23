#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys


def load_config(path):
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_item(item):
    ah_id = item.get("ah_id") or item.get("ah_product_id") or item.get("ahProductId")
    picnic_id = item.get("picnic_id") or item.get("picnic_product_id") or item.get("picnicProductId")
    qty = item.get("qty") or item.get("quantity") or 1
    name = item.get("name")

    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1

    if qty < 1:
        qty = 1

    try:
        if ah_id is not None:
            ah_id = int(ah_id)
    except (TypeError, ValueError):
        ah_id = None

    if picnic_id is not None:
        picnic_id = str(picnic_id)

    return {
        "name": name,
        "qty": qty,
        "ah_id": ah_id,
        "picnic_id": picnic_id,
    }


def parse_money_string(value):
    s = str(value).strip()
    s = s.replace("EUR", "").replace("€", "").strip()
    s = re.sub(r"[^0-9,.-]", "", s)

    if not s:
        return 0.0

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    return float(s)


def parse_ah_total(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return parse_money_string(value)


def parse_picnic_total(value, unit):
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        n = float(value)
        if unit == "cents":
            return n / 100.0
        return n

    return parse_money_string(value)


def run_json_command(command, stdin_text=None):
    completed = subprocess.run(
        command,
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown error"
        raise RuntimeError(f"Command failed ({' '.join(command)}): {detail}")

    stdout = completed.stdout.strip()
    if not stdout:
        return {}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON output from {' '.join(command)}: {exc}")


def resolve_paths(args, config):
    cli_paths = config.get("cli_paths", {}) if isinstance(config, dict) else {}

    appie_cli = args.appie_cli or cli_paths.get("appie_cli") or "appie-cli"
    node_bin = args.node or cli_paths.get("node") or "node"
    picnic_cli = (
        args.picnic_cli
        or cli_paths.get("picnic_cli")
        or os.environ.get("PICNIC_CLI_PATH")
    )

    if not picnic_cli:
        raise RuntimeError(
            "Picnic CLI path not configured. Set --picnic-cli or config.json cli_paths.picnic_cli"
        )

    return {
        "appie_cli": appie_cli,
        "node": node_bin,
        "picnic_cli": picnic_cli,
    }


def fetch_ah_order(paths):
    return run_json_command([paths["appie_cli"], "order"])


def fetch_picnic_cart(paths):
    return run_json_command([paths["node"], paths["picnic_cli"], "cart"])


def build_compare_report(ah_data, picnic_data, picnic_unit):
    ah_total = parse_ah_total(ah_data.get("totalPrice"))
    ah_discount = parse_ah_total(ah_data.get("totalDiscount", 0))
    ah_count = ah_data.get("totalCount", len(ah_data.get("items", [])))

    picnic_total = parse_picnic_total(picnic_data.get("totalPrice"), picnic_unit)
    picnic_count = picnic_data.get("itemCount", len(picnic_data.get("items", [])))

    if ah_total < picnic_total:
        recommendation = "albert_heijn"
        savings = picnic_total - ah_total
    elif picnic_total < ah_total:
        recommendation = "picnic"
        savings = ah_total - picnic_total
    else:
        recommendation = "either"
        savings = 0.0

    return {
        "ah": {
            "total": round(ah_total, 2),
            "discount": round(ah_discount, 2),
            "item_count": ah_count,
        },
        "picnic": {
            "total": round(picnic_total, 2),
            "item_count": picnic_count,
            "total_unit_assumption": picnic_unit,
        },
        "recommendation": recommendation,
        "savings": round(savings, 2),
    }


def read_items(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise RuntimeError("Items file must be a JSON array")
    return [normalize_item(item) for item in data]


def cmd_search_both(args, paths):
    ah_results = run_json_command([paths["appie_cli"], "search", args.query, str(args.limit)])
    picnic_results = run_json_command([paths["node"], paths["picnic_cli"], "search", args.query])

    normalized_ah = []
    for product in ah_results[: args.limit]:
        normalized_ah.append(
            {
                "id": product.get("id"),
                "name": product.get("title"),
                "price_now": (product.get("price") or {}).get("now"),
                "price_was": (product.get("price") or {}).get("was"),
                "is_bonus": product.get("isBonus"),
                "bonus_mechanism": product.get("bonusMechanism"),
                "unit_size": product.get("unitSize"),
            }
        )

    normalized_picnic = []
    for product in (picnic_results.get("products") or [])[: args.limit]:
        normalized_picnic.append(
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "price": product.get("price"),
                "unit": product.get("unit"),
                "available": product.get("available"),
            }
        )

    print(
        json.dumps(
            {
                "query": args.query,
                "ah": normalized_ah,
                "picnic": normalized_picnic,
            },
            indent=2,
        )
    )


def cmd_add_both(args, paths):
    if not args.yes and not args.dry_run:
        raise RuntimeError("Mutating command requires --yes")

    items = read_items(args.items_file)

    ah_batch = []
    picnic_items = []
    skipped = []

    for item in items:
        if not item["ah_id"] and not item["picnic_id"]:
            skipped.append({"reason": "missing both ah_id and picnic_id", "item": item})
            continue

        if item["ah_id"]:
            ah_batch.append({"id": item["ah_id"], "qty": item["qty"]})
        if item["picnic_id"]:
            picnic_items.append({"id": item["picnic_id"], "qty": item["qty"], "name": item["name"]})

    result = {
        "dry_run": args.dry_run,
        "planned": {
            "ah_count": len(ah_batch),
            "picnic_count": len(picnic_items),
            "skipped_count": len(skipped),
        },
        "skipped": skipped,
        "ah": None,
        "picnic": [],
    }

    if args.dry_run:
        result["ah"] = {"planned_items": ah_batch}
        result["picnic"] = [{"planned_item": item} for item in picnic_items]
        print(json.dumps(result, indent=2))
        return

    if ah_batch:
        ah_response = run_json_command(
            [paths["appie_cli"], "batch-add-to-order"],
            stdin_text=json.dumps(ah_batch),
        )
        result["ah"] = ah_response
    else:
        result["ah"] = {"ok": True, "added": 0}

    for item in picnic_items:
        response = run_json_command(
            [
                paths["node"],
                paths["picnic_cli"],
                "add",
                item["id"],
                str(item["qty"]),
                "--yes",
            ]
        )
        result["picnic"].append(
            {
                "id": item["id"],
                "qty": item["qty"],
                "name": item["name"],
                "response": response,
            }
        )

    print(json.dumps(result, indent=2))


def cmd_cart_both(_, paths):
    ah = fetch_ah_order(paths)
    picnic = fetch_picnic_cart(paths)
    print(json.dumps({"ah": ah, "picnic": picnic}, indent=2))


def cmd_compare_checkout(args, paths, config):
    picnic_defaults = config.get("picnic", {}) if isinstance(config, dict) else {}
    picnic_unit = args.picnic_unit or picnic_defaults.get("price_unit") or "cents"

    ah = fetch_ah_order(paths)
    picnic = fetch_picnic_cart(paths)
    report = build_compare_report(ah, picnic, picnic_unit)

    output = {
        "report": report,
        "checkout_action": {
            "recommended_store": report["recommendation"],
            "message": (
                "Checkout in Albert Heijn app"
                if report["recommendation"] == "albert_heijn"
                else "Checkout in Picnic app"
                if report["recommendation"] == "picnic"
                else "Either app has the same total"
            ),
        },
    }

    if args.include_carts:
        output["carts"] = {"ah": ah, "picnic": picnic}

    print(json.dumps(output, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Bridge commands for Albert Heijn + Picnic cart workflow"
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config file (default: config.json)",
    )
    parser.add_argument("--appie-cli", help="Path to appie-cli binary")
    parser.add_argument("--node", help="Path to node binary")
    parser.add_argument("--picnic-cli", help="Path to picnic-cli.mjs")

    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search-both", help="Search AH and Picnic")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=5, help="Results per store")

    add_parser = subparsers.add_parser("add-both", help="Add items to AH and Picnic carts")
    add_parser.add_argument(
        "--items-file",
        required=True,
        help="JSON array with items: ah_id/picnic_id/qty/name",
    )
    add_parser.add_argument("--yes", action="store_true", help="Confirm cart mutations")
    add_parser.add_argument("--dry-run", action="store_true", help="Show planned actions only")

    subparsers.add_parser("cart-both", help="Fetch current AH and Picnic carts")

    compare_parser = subparsers.add_parser(
        "compare-checkout",
        help="Compare current AH and Picnic cart totals",
    )
    compare_parser.add_argument(
        "--picnic-unit",
        choices=["cents", "eur"],
        help="How to interpret Picnic numeric totals",
    )
    compare_parser.add_argument(
        "--include-carts",
        action="store_true",
        help="Include raw cart payloads in output",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        paths = resolve_paths(args, config)

        if args.command == "search-both":
            cmd_search_both(args, paths)
            return
        if args.command == "add-both":
            cmd_add_both(args, paths)
            return
        if args.command == "cart-both":
            cmd_cart_both(args, paths)
            return
        if args.command == "compare-checkout":
            cmd_compare_checkout(args, paths, config)
            return

        raise RuntimeError(f"Unknown command: {args.command}")
    except Exception as exc:  # pylint: disable=broad-except
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
