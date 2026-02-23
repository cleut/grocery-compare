# Grocery Compare Skill (Albert Heijn + Picnic)

Bonus-aware grocery comparison between Albert Heijn and Picnic.

This skill is built for one main workflow:
1. Build and maintain carts for both stores from a grocery request
2. Match equivalent products with strict confidence rules
3. Compare checkout totals and recommend the cheaper app

Use `grocery-bridge.py` as the primary interface.
Use `appie-cli` only for Albert Heijn auth and low-level AH operations when needed.

## Scope

Use this skill for:
- Cross-store product matching (AH vs Picnic)
- Bonus-aware total comparison at checkout
- Updating both carts after explicit user approval

Do not use this skill for:
- Meal planning
- Recipe suggestions
- Taste profile learning
- Purchase-history analysis loops

## First-Time Setup

### 1) Build appie-cli

From this skill directory:

```bash
cd appie-cli
go build -o appie-cli .
mv appie-cli ~/go/bin/
```

Verify it works:

```bash
appie-cli search "kaas" 3
```

### 2) Login to Albert Heijn

Preferred:

```bash
appie-cli login
```

Fallback:

```bash
appie-cli login-url
appie-cli exchange-code "appie://login-exit?code=XXXXX"
```

### 3) Login to Picnic

Example:

```bash
node /absolute/path/to/picnic/cli.js login <email> NL
```

### 4) Configure local files

```bash
cp config-template.json config.json
```

Optional helper files:

```bash
cp weekly-basics-template.json weekly-basics.json
cp product-cache-template.json product-cache.json
```

Required config fields:
- `cli_paths.appie_cli`
- `cli_paths.node`
- `cli_paths.picnic_cli` (path to your Picnic CLI script, for example `cli.js`)

Optional tuning:
- `matching.*` thresholds for strict matching

## Core Workflow

### Phase 1) Build carts

1) Collect grocery intent from user (item names + quantities).

2) Match items across both stores:

```bash
python3 grocery-bridge.py --config config.json match-items --items-json '[{"name":"Halfvolle melk","qty":2},{"name":"Bananen","qty":1}]'
```

3) If any item is unresolved (low or medium confidence), present alternatives and ask user to choose.

4) After approval, update both carts:

```bash
python3 grocery-bridge.py --config config.json add-both --items-json '[{"name":"Halfvolle melk","qty":2},{"name":"Bananen","qty":1}]' --auto-match --yes
```

Strict rule: `add-both --auto-match` is all-or-nothing. If any item is unresolved, no cart mutations are applied.

Default workflow rule: prefer `grocery-bridge.py` commands over direct store-specific commands.

5) Verify both carts:

```bash
python3 grocery-bridge.py --config config.json cart-both
```

### Phase 2) Compare at checkout

Right before checkout:

```bash
python3 grocery-bridge.py --config config.json compare-checkout
```

Optional:
- add `--include-carts` to include raw cart payloads
- use `--picnic-unit eur` if Picnic totals are already in euros

## API Reference (grocery-bridge)

| Command | What it does |
|---------|-------------|
| `search-both <query> [--limit N]` | Search AH and Picnic in one call |
| `match-items (--items-file|--items-json|--items-stdin)` | Resolve names to AH/Picnic IDs with confidence |
| `add-both (--items-file|--items-json|--items-stdin) --auto-match --yes` | Add to both carts only when all items resolve |
| `cart-both` | Return both carts |
| `compare-checkout [--picnic-unit cents|eur]` | Compare totals and recommend checkout app |

## Advanced: API Reference (appie-cli)

| Command | What it does | Auth needed? |
|---------|-------------|--------------|
| `search <query> [limit]` | Search products | No |
| `product <id>` | Product details | No |
| `bonus-products [limit]` | Current bonus products | No |
| `order` | View active AH order cart | Yes |
| `order-summary` | View active AH order totals | Yes |
| `add-to-order <id> [qty]` | Add product to AH order cart | Yes |
| `batch-add-to-order` | Add multiple products to AH order cart from stdin JSON | Yes |
| `remove-from-order <id>` | Remove product from AH order cart | Yes |
| `clear-order` | Clear active AH order cart | Yes |
| `shopping-list` | View primary shopping list | Yes |
| `shopping-lists` | List all shopping lists | Yes |
| `list-items <list-id>` | Items in specific list | Yes |
| `add-to-list <id> [qty]` | Add product to list | Yes |
| `add-to-list --text "item" [qty]` | Add free text item | Yes |
| `batch-add` | Add multiple items from stdin JSON | Yes |
| `clear-list` | Clear shopping list | Yes |

## Files

- `config.json` - local runtime config (copy from `config-template.json`)
- `weekly-basics.json` - optional recurring groceries
- `product-cache.json` - optional AH product lookup cache
- `match-cache.json` - cached cross-store matches
- `grocery-bridge.py` - primary AH+Picnic integration layer
- `checkout-compare.py` - optional file-based compare helper
- `.appie.json` - AH auth tokens (never commit)

## Important Rules

- Never mutate AH cart/list or Picnic cart without explicit user approval
- Prefer exact same-product matches; ask user when confidence is not high
- Always surface AH bonus context in price explanations
- Keep assumptions transparent (unit size, package, quantity)
