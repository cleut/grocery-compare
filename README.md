# OpenClaw Skill: Grocery Compare (Albert Heijn + Picnic)

> Unofficial integration. Not affiliated with, endorsed by, or connected to Albert Heijn or Ahold Delhaize.

This skill compares Albert Heijn and Picnic for weekly groceries.
It uses `grocery-bridge.py` to orchestrate both stores through `appie-cli` and your Picnic CLI script.

Use it to:
- add groceries to both carts during the week
- compare both carts at checkout time
- choose the cheaper app for final purchase

## What This Skill Does

1. Connect to Albert Heijn and Picnic CLIs
2. Match products across both stores with strict confidence rules
3. Build both carts from one grocery intent list
4. Compare checkout totals with AH bonus context and recommend where to buy

Out of scope:
- meal suggestions
- recipe workflows
- taste profile learning
- purchase-history analysis loops

## Quick Start

### 1) Build CLI

Requires Go 1.23+:

```bash
cd appie-cli
go build -o appie-cli .
mv appie-cli ~/go/bin/
```

### 2) Login to Albert Heijn

```bash
appie-cli login
```

This starts a local page that guides login and exchanges the auth code automatically.

Manual fallback:

```bash
appie-cli login-url
appie-cli exchange-code <code-or-appie-url>
```

### 3) Login to Picnic

```bash
node /absolute/path/to/picnic/cli.js login <email> NL
```

### 4) Create local config file

```bash
cp config-template.json config.json
```

Set `cli_paths.picnic_cli` in `config.json` to your local Picnic CLI script path (for example `cli.js` or `picnic-cli.mjs`).
Tune strict matching behavior in `config.json` under `matching` (thresholds, score gap, cache TTL).

Optional helper files (only if you use them):

```bash
cp weekly-basics-template.json weekly-basics.json
cp product-cache-template.json product-cache.json
```

## Typical Combined Flow (Picnic + AH)

Phase 1: Build carts
1. User provides desired groceries (plain names are allowed)
2. Agent resolves matches with strict same-product logic (`grocery-bridge.py match-items`)
3. User reviews low/medium confidence items
4. Agent adds to both carts with auto-match (`grocery-bridge.py add-both --auto-match --yes`)

Phase 2: Checkout compare
1. Fetch both carts and compare totals
2. Review recommendation and savings
3. User checks out in the cheaper app

Example flow:

```bash
python3 grocery-bridge.py --config config.json match-items --items-json '[{"name":"Halfvolle melk","qty":2},{"name":"Bananen","qty":1}]'
python3 grocery-bridge.py --config config.json add-both --items-json '[{"name":"Halfvolle melk","qty":2},{"name":"Bananen","qty":1}]' --auto-match --yes
python3 grocery-bridge.py --config config.json compare-checkout
```

File-based flow (optional):

```bash
python3 grocery-bridge.py --config config.json match-items --items-file items.json
python3 grocery-bridge.py --config config.json add-both --items-file items.json --auto-match --yes
```

`items.json` example:

```json
[
  {"name": "Halfvolle melk", "qty": 2},
  {"name": "Bananen", "qty": 1},
  {"name": "Coca-Cola Zero", "qty": 1, "ah_id": 216934, "picnic_id": "s998877"}
]
```

`add-both --auto-match` is strict: if any item remains unresolved (low or medium confidence), it aborts all cart mutations.

## Bridge Commands

```text
python3 grocery-bridge.py [global options] <command>

Global options:
  --config <path>              Config file (default: config.json)
  --appie-cli <path>           Override appie-cli path
  --node <path>                Override node path
  --picnic-cli <path>          Override Picnic CLI script path

Commands:
  search-both <query> [--limit 5]              Search AH and Picnic
  match-items (--items-file f | --items-json j | --items-stdin)  Resolve names to AH/Picnic IDs
  add-both (--items-file f | --items-json j | --items-stdin) [--auto-match] [--yes]  Add products to both carts
  cart-both                                    Fetch both carts
  compare-checkout [--picnic-unit cents|eur]   Compare totals and recommend checkout app
```

## Advanced: appie-cli Commands (AH-only)

```text
appie-cli <command> [args]

Auth:
  login                         Login via local web flow
  login-url                     Get AH login URL (manual flow)
  exchange-code <code-or-url>   Exchange auth code

Products:
  search <query> [limit]        Search products
  product <id>                  Product details
  bonus                         Spotlight bonus products
  bonus-products [limit]        Bonus products from product search endpoint

Shopping List:
  shopping-list                 Show main shopping list
  shopping-lists                List all shopping lists
  list-items <list-id>          Show items for a specific list
  add-to-list <id> [qty]        Add product
  add-to-list --text "item"     Add free text item
  batch-add                     Add multiple items from stdin JSON array
  clear-list                    Clear shopping list

Order (Cart):
  order                         Show current order cart
  order-summary                 Show current order totals
  add-to-order <id> [qty]       Add product to cart
  batch-add-to-order            Add multiple products from stdin JSON
  remove-from-order <id>        Remove product from cart
  clear-order                   Clear cart
```

## Notes

- `bonus-products` can be used without login (anonymous token)
- auth tokens are stored in `.appie.json` (ignored by git)
- match cache is stored in `match-cache.json` (ignored by git)
- final checkout/payment for Picnic is done in the Picnic app
- `grocery-bridge.py` is the native integration layer for Picnic + Albert Heijn
- `checkout-compare.py` is an optional file-based compare helper

## License

AGPL-3.0
