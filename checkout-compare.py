#!/usr/bin/env python3

import argparse
import json
import re
import sys


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}")


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


def fmt_eur(amount):
    return f"EUR {amount:.2f}"


def build_report(ah_data, picnic_data, picnic_unit):
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


def print_text_report(report):
    print("Checkout comparison")
    print(f"- Albert Heijn: {fmt_eur(report['ah']['total'])} ({report['ah']['item_count']} items)")
    print(
        f"- AH discount included: {fmt_eur(report['ah']['discount'])}"
    )
    print(
        f"- Picnic: {fmt_eur(report['picnic']['total'])} ({report['picnic']['item_count']} items, unit={report['picnic']['total_unit_assumption']})"
    )

    rec = report["recommendation"]
    if rec == "either":
        print("- Recommendation: either (same total)")
    elif rec == "albert_heijn":
        print(f"- Recommendation: buy in Albert Heijn app (save {fmt_eur(report['savings'])})")
    else:
        print(f"- Recommendation: buy in Picnic app (save {fmt_eur(report['savings'])})")


def main():
    parser = argparse.ArgumentParser(
        description="Compare checkout totals from AH order JSON and Picnic cart JSON"
    )
    parser.add_argument("--ah", required=True, help="Path to appie-cli order output JSON")
    parser.add_argument("--picnic", required=True, help="Path to picnic cart output JSON")
    parser.add_argument(
        "--picnic-unit",
        choices=["cents", "eur"],
        default="cents",
        help="How to interpret numeric Picnic totals (default: cents)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )

    args = parser.parse_args()

    try:
        ah_data = read_json_file(args.ah)
        picnic_data = read_json_file(args.picnic)
        report = build_report(ah_data, picnic_data, args.picnic_unit)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return

    print_text_report(report)


if __name__ == "__main__":
    main()
