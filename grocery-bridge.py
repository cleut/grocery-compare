#!/usr/bin/env python3

import argparse
import datetime as dt
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata


DEFAULT_MATCHING = {
    "search_limit": 8,
    "auto_accept_score": 72,
    "min_score_gap": 8,
    "prefer_bonus_tiebreak": True,
    "cache_file": "match-cache.json",
    "cache_ttl_days": 21,
    "max_alternatives": 3,
}

STOPWORDS = {
    "de",
    "het",
    "een",
    "en",
    "van",
    "voor",
    "met",
    "zonder",
    "per",
    "stuk",
    "stuks",
    "x",
}

UNIT_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|gram|grams|l|liter|litre|ml|cl|stuks?|stuk|x)\b",
    re.IGNORECASE,
)

MULTIPACK_PATTERN = re.compile(
    r"(\d+)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|cl)\b",
    re.IGNORECASE,
)


class BridgeError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload


def load_config(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_matching_settings(config, override_limit=None):
    settings = dict(DEFAULT_MATCHING)
    if isinstance(config, dict):
        settings.update(config.get("matching", {}))
        config_dir = config.get("__config_dir")
        cache_file = settings.get("cache_file")
        if config_dir and cache_file and not os.path.isabs(cache_file):
            settings["cache_file"] = os.path.join(config_dir, cache_file)
    if override_limit:
        settings["search_limit"] = override_limit
    return settings


def normalize_item(item):
    if not isinstance(item, dict):
        item = {"name": str(item)}

    ah_id = item.get("ah_id") or item.get("ah_product_id") or item.get("ahProductId")
    picnic_id = item.get("picnic_id") or item.get("picnic_product_id") or item.get("picnicProductId")
    qty = item.get("qty") or item.get("quantity") or 1

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

    name = item.get("name")
    if isinstance(name, str):
        name = name.strip()

    brand = item.get("brand")
    if isinstance(brand, str):
        brand = brand.strip()

    unit_hint = item.get("unit") or item.get("unit_hint") or item.get("size")
    if isinstance(unit_hint, str):
        unit_hint = unit_hint.strip()

    return {
        "name": name,
        "qty": qty,
        "ah_id": ah_id,
        "picnic_id": picnic_id,
        "brand": brand,
        "unit_hint": unit_hint,
    }


def strip_accents(value):
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value):
    if value is None:
        return ""
    text = strip_accents(str(value).lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value):
    tokens = normalize_text(value).split(" ")
    return [token for token in tokens if token and token not in STOPWORDS]


def parse_float(part):
    return float(part.replace(",", "."))


def parse_unit_hint(*values):
    for value in values:
        if not value or not isinstance(value, str):
            continue
        text = normalize_text(value)

        multipack = MULTIPACK_PATTERN.search(text)
        if multipack:
            count = parse_float(multipack.group(1))
            amount = parse_float(multipack.group(2))
            unit = multipack.group(3).lower()
            if unit == "kg":
                amount = amount * 1000.0
                unit = "g"
            elif unit == "l":
                amount = amount * 1000.0
                unit = "ml"
            elif unit == "cl":
                amount = amount * 10.0
                unit = "ml"
            return {
                "value": count * amount,
                "unit": unit,
                "raw": multipack.group(0),
            }

        match = UNIT_PATTERN.search(text)
        if not match:
            continue

        amount = parse_float(match.group(1))
        unit = match.group(2).lower()
        if unit in {"gram", "grams"}:
            unit = "g"
        if unit in {"liter", "litre"}:
            unit = "l"

        if unit == "kg":
            amount = amount * 1000.0
            unit = "g"
        elif unit == "l":
            amount = amount * 1000.0
            unit = "ml"
        elif unit == "cl":
            amount = amount * 10.0
            unit = "ml"
        elif unit in {"stuk", "stuks", "x"}:
            unit = "count"

        return {
            "value": amount,
            "unit": unit,
            "raw": match.group(0),
        }

    return None


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
        return n / 100.0 if unit == "cents" else n
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
        raise BridgeError(
            "command_failed",
            payload={
                "error": "command_failed",
                "command": command,
                "detail": detail,
            },
        )

    stdout = completed.stdout.strip()
    if not stdout:
        return {}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BridgeError(
            "invalid_json_output",
            payload={
                "error": "invalid_json_output",
                "command": command,
                "detail": str(exc),
                "stdout_preview": stdout[:300],
            },
        )


def resolve_paths(args, config):
    cli_paths = config.get("cli_paths", {}) if isinstance(config, dict) else {}

    appie_cli = args.appie_cli or cli_paths.get("appie_cli") or "appie-cli"
    node_bin = args.node or cli_paths.get("node") or "node"
    picnic_cli = args.picnic_cli or cli_paths.get("picnic_cli") or os.environ.get("PICNIC_CLI_PATH")

    if not picnic_cli:
        raise BridgeError(
            "missing_picnic_cli",
            payload={
                "error": "missing_picnic_cli",
                "detail": "Set --picnic-cli or config.json cli_paths.picnic_cli",
            },
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


def parse_items_payload(data, source):
    if not isinstance(data, list):
        raise BridgeError(
            "invalid_items_payload",
            payload={
                "error": "invalid_items_payload",
                "detail": f"Expected JSON array for {source}",
                "hint": "Provide an array like [{\"name\": \"bananen\", \"qty\": 1}]",
            },
        )
    return [normalize_item(item) for item in data]


def read_items_from_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise BridgeError(
            "missing_items_file",
            payload={
                "error": "missing_items_file",
                "detail": f"File not found: {path}",
                "hint": "Create the file first, or use --items-json / --items-stdin",
            },
        )
    except json.JSONDecodeError as exc:
        raise BridgeError(
            "invalid_items_json",
            payload={
                "error": "invalid_items_json",
                "detail": f"Invalid JSON in {path}: {exc}",
                "hint": "Fix JSON syntax or use --items-json / --items-stdin",
            },
        )
    except OSError as exc:
        raise BridgeError(
            "items_file_read_error",
            payload={
                "error": "items_file_read_error",
                "detail": str(exc),
            },
        )
    return parse_items_payload(data, f"file '{path}'")


def read_items_from_inline_json(raw_json, source):
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise BridgeError(
            "invalid_items_json",
            payload={
                "error": "invalid_items_json",
                "detail": f"Invalid JSON for {source}: {exc}",
                "hint": "Example: --items-json '[{\"name\":\"bananen\",\"qty\":1}]'",
            },
        )
    return parse_items_payload(data, source)


def read_items_from_stdin():
    raw = sys.stdin.read()
    if not raw.strip():
        raise BridgeError(
            "empty_stdin",
            payload={
                "error": "empty_stdin",
                "detail": "No input received on stdin",
                "hint": "Pipe JSON array to stdin, for example: echo '[{\"name\":\"bananen\",\"qty\":1}]' | ... --items-stdin",
            },
        )
    return read_items_from_inline_json(raw, "stdin")


def read_items_from_args(args):
    if getattr(args, "items_file", None):
        return read_items_from_file(args.items_file)
    if getattr(args, "items_json", None):
        return read_items_from_inline_json(args.items_json, "--items-json")
    if getattr(args, "items_stdin", False):
        return read_items_from_stdin()
    raise BridgeError(
        "missing_items_input",
        payload={
            "error": "missing_items_input",
            "detail": "Provide one of --items-file, --items-json, or --items-stdin",
        },
    )


def score_name_similarity(query_name, candidate_name):
    q_norm = normalize_text(query_name)
    c_norm = normalize_text(candidate_name)

    if not q_norm or not c_norm:
        return 0.0, {"token_overlap": 0.0, "sequence_ratio": 0.0, "exact": False}

    exact = q_norm == c_norm

    q_tokens = set(tokenize(query_name))
    c_tokens = set(tokenize(candidate_name))
    if q_tokens and c_tokens:
        token_overlap = len(q_tokens & c_tokens) / float(len(q_tokens | c_tokens))
    else:
        token_overlap = 0.0

    sequence_ratio = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()

    score = token_overlap * 60.0 + sequence_ratio * 35.0
    if exact:
        score = 100.0

    return score, {
        "token_overlap": round(token_overlap, 3),
        "sequence_ratio": round(sequence_ratio, 3),
        "exact": exact,
    }


def score_unit_compatibility(item, candidate):
    query_hint = parse_unit_hint(item.get("unit_hint"), item.get("name"))
    candidate_hint = parse_unit_hint(candidate.get("unit_size"), candidate.get("name"))

    if not query_hint:
        return 0.0, "no_query_unit_hint"

    if not candidate_hint:
        return -6.0, "missing_candidate_unit"

    if query_hint["unit"] != candidate_hint["unit"]:
        return -20.0, "unit_mismatch"

    query_value = query_hint["value"]
    candidate_value = candidate_hint["value"]
    if query_value <= 0:
        return 0.0, "invalid_query_unit"

    delta = abs(candidate_value - query_value) / query_value
    if delta <= 0.10:
        return 15.0, "unit_close"
    if delta <= 0.25:
        return 8.0, "unit_reasonable"
    if delta <= 0.50:
        return 2.0, "unit_far"
    return -10.0, "unit_very_far"


def score_brand_compatibility(item, candidate):
    brand = item.get("brand")
    if not brand:
        return 0.0, "no_brand_hint"

    brand_norm = normalize_text(brand)
    cand_name = normalize_text(candidate.get("name"))
    cand_brand = normalize_text(candidate.get("brand"))

    if brand_norm and (brand_norm in cand_name or brand_norm in cand_brand):
        return 10.0, "brand_match"
    return -6.0, "brand_mismatch"


def score_availability(candidate):
    available = candidate.get("available")
    if available is False:
        return -25.0, "not_available"
    return 0.0, "available_or_unknown"


def score_bonus_tiebreak(candidate, settings):
    if not settings.get("prefer_bonus_tiebreak", True):
        return 0.0, "bonus_tiebreak_disabled"
    if candidate.get("is_bonus"):
        return 2.0, "bonus_tiebreak"
    return 0.0, "no_bonus"


def score_candidate(item, candidate, settings):
    name_score, name_meta = score_name_similarity(item.get("name"), candidate.get("name"))
    unit_score, unit_reason = score_unit_compatibility(item, candidate)
    brand_score, brand_reason = score_brand_compatibility(item, candidate)
    availability_score, availability_reason = score_availability(candidate)
    bonus_score, bonus_reason = score_bonus_tiebreak(candidate, settings)

    total = name_score + unit_score + brand_score + availability_score + bonus_score
    if total < 0:
        total = 0.0
    if total > 100:
        total = 100.0

    return {
        "id": candidate.get("id"),
        "name": candidate.get("name"),
        "brand": candidate.get("brand"),
        "unit_size": candidate.get("unit_size"),
        "available": candidate.get("available"),
        "is_bonus": candidate.get("is_bonus", False),
        "score": round(total, 2),
        "score_breakdown": {
            "name": round(name_score, 2),
            "unit": round(unit_score, 2),
            "brand": round(brand_score, 2),
            "availability": round(availability_score, 2),
            "bonus_tiebreak": round(bonus_score, 2),
            "name_meta": name_meta,
            "unit_reason": unit_reason,
            "brand_reason": brand_reason,
            "availability_reason": availability_reason,
            "bonus_reason": bonus_reason,
        },
    }


def choose_best_match(scored_candidates, settings):
    if not scored_candidates:
        return {
            "resolved": False,
            "confidence": "low",
            "score": 0,
            "score_gap": 0,
            "selected": None,
            "alternatives": [],
            "reason": "no_candidates",
        }

    sorted_candidates = sorted(scored_candidates, key=lambda c: c["score"], reverse=True)
    top = sorted_candidates[0]
    second_score = sorted_candidates[1]["score"] if len(sorted_candidates) > 1 else 0.0
    score_gap = round(top["score"] - second_score, 2)

    auto_accept_score = float(settings.get("auto_accept_score", 72))
    min_score_gap = float(settings.get("min_score_gap", 8))

    if top["score"] >= auto_accept_score and score_gap >= min_score_gap:
        confidence = "high"
        resolved = True
        reason = "high_confidence"
    elif top["score"] >= auto_accept_score:
        confidence = "medium"
        resolved = False
        reason = "score_gap_too_small"
    elif top["score"] >= auto_accept_score - 10:
        confidence = "medium"
        resolved = False
        reason = "score_below_auto_accept"
    else:
        confidence = "low"
        resolved = False
        reason = "low_score"

    alternatives = sorted_candidates[1 : int(settings.get("max_alternatives", 3)) + 1]

    return {
        "resolved": resolved,
        "confidence": confidence,
        "score": top["score"],
        "score_gap": score_gap,
        "selected": top,
        "alternatives": alternatives,
        "reason": reason,
    }


def normalize_ah_product(product):
    return {
        "id": product.get("id"),
        "name": product.get("title"),
        "brand": product.get("brand"),
        "unit_size": product.get("unitSize") or (product.get("price") or {}).get("unitSize"),
        "available": product.get("isOrderable") if product.get("isOrderable") is not None else product.get("isAvailable"),
        "is_bonus": bool(product.get("isBonus")),
        "price_now": (product.get("price") or {}).get("now"),
        "price_was": (product.get("price") or {}).get("was"),
        "bonus_mechanism": product.get("bonusMechanism"),
    }


def normalize_picnic_product(product):
    return {
        "id": product.get("id"),
        "name": product.get("name"),
        "brand": None,
        "unit_size": product.get("unit"),
        "available": product.get("available"),
        "is_bonus": False,
        "price": product.get("price"),
    }


def cache_key_for_item(item):
    name = normalize_text(item.get("name"))
    brand = normalize_text(item.get("brand"))
    unit = normalize_text(item.get("unit_hint"))
    return "|".join([name, brand, unit]).strip("|")


def load_match_cache(path):
    if not path or not os.path.exists(path):
        return {"items": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"items": {}}
        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return {"items": {}}


def save_match_cache(path, cache):
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2)


def cache_entry_is_valid(entry, ttl_days):
    if not entry or not isinstance(entry, dict):
        return False
    updated_at = entry.get("updated_at")
    if not updated_at:
        return False
    try:
        updated_dt = dt.datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    max_age = dt.timedelta(days=int(ttl_days))
    return dt.datetime.utcnow() - updated_dt <= max_age


def search_ah(paths, query, limit):
    raw = run_json_command([paths["appie_cli"], "search", query, str(limit)])
    return [normalize_ah_product(product) for product in raw[:limit]]


def search_picnic(paths, query):
    raw = run_json_command([paths["node"], paths["picnic_cli"], "search", query])
    return [normalize_picnic_product(product) for product in (raw.get("products") or [])]


def resolve_store_match(store_name, item, query, settings, paths, cached_entry, allow_cache):
    manual_id_key = "ah_id" if store_name == "ah" else "picnic_id"
    cache_id_key = "ah_id" if store_name == "ah" else "picnic_id"
    cache_name_key = "ah_name" if store_name == "ah" else "picnic_name"

    manual_id = item.get(manual_id_key)
    if manual_id:
        return {
            "resolved": True,
            "confidence": "manual",
            "score": 100.0,
            "score_gap": 100.0,
            "reason": "manual_id",
            "selected": {"id": manual_id, "name": None, "score": 100.0},
            "alternatives": [],
            "from_cache": False,
        }

    if allow_cache and cached_entry and cache_entry_is_valid(cached_entry, settings.get("cache_ttl_days", 21)):
        cached_id = cached_entry.get(cache_id_key)
        if cached_id:
            return {
                "resolved": True,
                "confidence": "high_cached",
                "score": 95.0,
                "score_gap": 95.0,
                "reason": "cache_hit",
                "selected": {
                    "id": cached_id,
                    "name": cached_entry.get(cache_name_key),
                    "score": 95.0,
                },
                "alternatives": [],
                "from_cache": True,
            }

    if not query:
        return {
            "resolved": False,
            "confidence": "low",
            "score": 0.0,
            "score_gap": 0.0,
            "reason": "missing_query",
            "selected": None,
            "alternatives": [],
            "from_cache": False,
        }

    if store_name == "ah":
        candidates = search_ah(paths, query, int(settings.get("search_limit", 8)))
    else:
        candidates = search_picnic(paths, query)[: int(settings.get("search_limit", 8))]

    scored = [score_candidate(item, candidate, settings) for candidate in candidates]
    decision = choose_best_match(scored, settings)
    decision["from_cache"] = False
    return decision


def match_items(items, paths, config, allow_cache=True, override_limit=None, save_cache_on_resolve=True):
    settings = get_matching_settings(config, override_limit=override_limit)

    cache_file = settings.get("cache_file")
    cache = load_match_cache(cache_file) if allow_cache else {"items": {}}
    cache_items = cache.get("items", {})

    matched_items = []
    unresolved_items = []
    resolved_items = []
    cache_hits = 0

    for item in items:
        query = item.get("name")
        key = cache_key_for_item(item)
        cached_entry = cache_items.get(key)

        ah_match = resolve_store_match("ah", item, query, settings, paths, cached_entry, allow_cache)
        picnic_match = resolve_store_match("picnic", item, query, settings, paths, cached_entry, allow_cache)

        if ah_match.get("from_cache"):
            cache_hits += 1
        if picnic_match.get("from_cache"):
            cache_hits += 1

        resolved = bool(ah_match.get("resolved") and picnic_match.get("resolved"))

        result_item = {
            "input": item,
            "cache_key": key,
            "resolved": resolved,
            "ah": ah_match,
            "picnic": picnic_match,
        }
        matched_items.append(result_item)

        if resolved:
            resolved_items.append(
                {
                    "name": item.get("name"),
                    "qty": item.get("qty", 1),
                    "ah_id": ah_match["selected"]["id"],
                    "picnic_id": picnic_match["selected"]["id"],
                }
            )

            if save_cache_on_resolve and key:
                cache_items[key] = {
                    "ah_id": ah_match["selected"]["id"],
                    "ah_name": ah_match["selected"].get("name"),
                    "picnic_id": picnic_match["selected"]["id"],
                    "picnic_name": picnic_match["selected"].get("name"),
                    "updated_at": dt.datetime.utcnow().isoformat(),
                }
        else:
            unresolved_items.append(
                {
                    "name": item.get("name"),
                    "qty": item.get("qty", 1),
                    "ah_confidence": ah_match.get("confidence"),
                    "picnic_confidence": picnic_match.get("confidence"),
                    "ah_reason": ah_match.get("reason"),
                    "picnic_reason": picnic_match.get("reason"),
                }
            )

    if allow_cache and save_cache_on_resolve:
        cache["items"] = cache_items
        save_match_cache(cache_file, cache)

    return {
        "settings": settings,
        "summary": {
            "total": len(items),
            "resolved": len(resolved_items),
            "unresolved": len(unresolved_items),
            "cache_hits": cache_hits,
        },
        "items": matched_items,
        "resolved_items": resolved_items,
        "unresolved_items": unresolved_items,
    }


def aggregate_ah_batch(items):
    counts = {}
    for item in items:
        pid = int(item["id"])
        qty = int(item.get("qty", 1))
        counts[pid] = counts.get(pid, 0) + qty
    return [{"id": pid, "qty": qty} for pid, qty in sorted(counts.items(), key=lambda x: x[0])]


def aggregate_picnic_batch(items):
    counts = {}
    names = {}
    for item in items:
        pid = str(item["id"])
        qty = int(item.get("qty", 1))
        counts[pid] = counts.get(pid, 0) + qty
        if item.get("name"):
            names[pid] = item["name"]
    result = []
    for pid, qty in sorted(counts.items(), key=lambda x: x[0]):
        result.append({"id": pid, "qty": qty, "name": names.get(pid)})
    return result


def cmd_search_both(args, paths):
    ah_results = search_ah(paths, args.query, args.limit)
    picnic_results = search_picnic(paths, args.query)[: args.limit]

    print(
        json.dumps(
            {
                "query": args.query,
                "ah": ah_results,
                "picnic": picnic_results,
            },
            indent=2,
        )
    )


def cmd_match_items(args, paths, config):
    items = read_items_from_args(args)
    result = match_items(
        items,
        paths,
        config,
        allow_cache=not args.no_cache,
        override_limit=args.search_limit,
        save_cache_on_resolve=not args.no_cache,
    )
    print(json.dumps(result, indent=2))


def cmd_add_both(args, paths, config):
    if not args.yes and not args.dry_run:
        raise BridgeError("confirmation_required", payload={"error": "Mutating command requires --yes"})

    items = read_items_from_args(args)

    if args.auto_match:
        match_result = match_items(
            items,
            paths,
            config,
            allow_cache=not args.no_cache,
            override_limit=args.search_limit,
            save_cache_on_resolve=not args.no_cache,
        )
        if match_result["summary"]["unresolved"] > 0:
            raise BridgeError(
                "unresolved_matches",
                payload={
                    "error": "unresolved_matches",
                    "detail": "No cart updates were applied. Resolve low/medium confidence matches first.",
                    "summary": match_result["summary"],
                    "unresolved_items": match_result["unresolved_items"],
                },
            )
        resolved = match_result["resolved_items"]
        ah_batch = aggregate_ah_batch([{"id": item["ah_id"], "qty": item["qty"]} for item in resolved])
        picnic_items = aggregate_picnic_batch(
            [
                {"id": item["picnic_id"], "qty": item["qty"], "name": item.get("name")}
                for item in resolved
            ]
        )
        skipped = []
    else:
        ah_raw = []
        picnic_raw = []
        skipped = []
        for item in items:
            if not item["ah_id"] and not item["picnic_id"]:
                skipped.append({"reason": "missing both ah_id and picnic_id", "item": item})
                continue
            if item["ah_id"]:
                ah_raw.append({"id": item["ah_id"], "qty": item["qty"]})
            if item["picnic_id"]:
                picnic_raw.append({"id": item["picnic_id"], "qty": item["qty"], "name": item["name"]})
        ah_batch = aggregate_ah_batch(ah_raw)
        picnic_items = aggregate_picnic_batch(picnic_raw)

    result = {
        "dry_run": args.dry_run,
        "auto_match": args.auto_match,
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
            [paths["node"], paths["picnic_cli"], "add", item["id"], str(item["qty"]), "--yes"]
        )
        result["picnic"].append(
            {
                "id": item["id"],
                "qty": item["qty"],
                "name": item.get("name"),
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
    parser.add_argument("--config", default="config.json", help="Path to config file (default: config.json)")
    parser.add_argument("--appie-cli", help="Path to appie-cli binary")
    parser.add_argument("--node", help="Path to node binary")
    parser.add_argument("--picnic-cli", help="Path to picnic-cli.mjs")

    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search-both", help="Search AH and Picnic")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=5, help="Results per store")

    match_parser = subparsers.add_parser("match-items", help="Auto-match plain grocery names to both stores")
    match_items_input = match_parser.add_mutually_exclusive_group(required=True)
    match_items_input.add_argument("--items-file", help="JSON array file with items")
    match_items_input.add_argument("--items-json", help="Inline JSON array with items")
    match_items_input.add_argument("--items-stdin", action="store_true", help="Read JSON array from stdin")
    match_parser.add_argument("--search-limit", type=int, help="Override configured search limit")
    match_parser.add_argument("--no-cache", action="store_true", help="Disable match-cache reads/writes")

    add_parser = subparsers.add_parser("add-both", help="Add items to AH and Picnic carts")
    add_items_input = add_parser.add_mutually_exclusive_group(required=True)
    add_items_input.add_argument("--items-file", help="JSON array file with items")
    add_items_input.add_argument("--items-json", help="Inline JSON array with items")
    add_items_input.add_argument("--items-stdin", action="store_true", help="Read JSON array from stdin")
    add_parser.add_argument("--yes", action="store_true", help="Confirm cart mutations")
    add_parser.add_argument("--dry-run", action="store_true", help="Show planned actions only")
    add_parser.add_argument("--auto-match", action="store_true", help="Auto-match names to both stores before adding")
    add_parser.add_argument("--search-limit", type=int, help="Override configured search limit")
    add_parser.add_argument("--no-cache", action="store_true", help="Disable match-cache reads/writes")

    subparsers.add_parser("cart-both", help="Fetch current AH and Picnic carts")

    compare_parser = subparsers.add_parser(
        "compare-checkout",
        help="Compare current AH and Picnic cart totals",
    )
    compare_parser.add_argument("--picnic-unit", choices=["cents", "eur"], help="How to interpret Picnic numeric totals")
    compare_parser.add_argument("--include-carts", action="store_true", help="Include raw cart payloads in output")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        if isinstance(config, dict):
            config["__config_dir"] = os.path.dirname(os.path.abspath(args.config))
        paths = resolve_paths(args, config)

        if args.command == "search-both":
            cmd_search_both(args, paths)
            return
        if args.command == "match-items":
            cmd_match_items(args, paths, config)
            return
        if args.command == "add-both":
            cmd_add_both(args, paths, config)
            return
        if args.command == "cart-both":
            cmd_cart_both(args, paths)
            return
        if args.command == "compare-checkout":
            cmd_compare_checkout(args, paths, config)
            return

        raise BridgeError("unknown_command", payload={"error": f"Unknown command: {args.command}"})
    except BridgeError as exc:
        if exc.payload:
            print(json.dumps(exc.payload, indent=2))
        else:
            print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
