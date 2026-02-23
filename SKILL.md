# Albert Heijn Grocery Skill

Albert Heijn companion skill focused on one job:

1. Build an Albert Heijn list or order cart from user-requested groceries
2. Keep AH and Picnic carts in sync during planning
3. Compare totals at checkout time and pick the cheaper app

This skill is designed to work together with the Picnic skill.

## Scope

Use this skill for:
- Product search and pricing at Albert Heijn
- Bonus-aware price comparison (AH vs Picnic)
- Building AH shopping lists or AH order cart after explicit user approval

Do not use this skill for:
- Meal planning
- Recipe suggestions
- Taste profiling
- Purchase-history learning flows

## First-Time Setup

You need Go installed and the user must log in to their AH account.

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

### 2) Login to AH (human interaction required)

Preferred:

```bash
appie-cli login
```

This starts a local page where the user logs in and pastes the `appie://...code=...` URL.

Fallback:

```bash
appie-cli login-url
appie-cli exchange-code "appie://login-exit?code=XXXXX"
```

Tokens are saved to `.appie.json` and auto-refresh.

### 3) Configure local files

```bash
cp config-template.json config.json
cp weekly-basics-template.json weekly-basics.json
cp product-cache-template.json product-cache.json
```

Fill `weekly-basics.json` with recurring products and AH product IDs.

## Cross-Skill Workflow (Picnic + AH)

Run this flow when the user wants to place a weekly order.

### Phase 1) Add groceries

### 1) Collect intent

Gather:
- Requested items + quantities
- Weekly basics (`weekly-basics.json`)
- Any fixed store preference from `config.json` (`always_picnic`, `always_ah`)

### 2) Get Albert Heijn candidates

For each item:

```bash
appie-cli search "<query>" 5
```

For bonus context:

```bash
appie-cli bonus-products 200
```

Use `product-cache.json` first to avoid repeated searches.

### 3) Get Picnic candidates

Use the Picnic skill commands (typically `search`, optionally `cart` for current state).

### 4) Match products for both stores

For each requested item:
- Choose best AH candidate and best Picnic candidate
- Normalize by package size or unit where possible
- Compute effective AH price from `price.now`
- Include AH bonus metadata (`isBonus`, `bonusMechanism`, `price.was`) in explanation

If matching is ambiguous, present top options and ask the user to pick before adding.

### 5) Present proposal (no mutations yet)

Show:
- Item-by-item recommendation (AH or Picnic)
- Unit/package assumptions
- Bonus notes for AH items
- Totals and estimated savings

Always wait for explicit approval before mutating either store list/cart.

### 6) Apply approved cart updates

Albert Heijn:
- For cart comparison and checkout planning, prefer the AH order cart:

```bash
echo '[{"id": 12345, "qty": 2}]' | appie-cli batch-add-to-order
appie-cli order
```

- For checklist-style planning, build one combined JSON batch and call:

```bash
appie-cli batch-add
```

Picnic:
- Add approved Picnic items using Picnic skill `add` commands

### Phase 2) Compare at checkout

Right before checkout, export both carts and compare totals:

```bash
appie-cli order > /tmp/ah-order.json
node /path/to/picnic-cli.mjs cart > /tmp/picnic-cart.json
python3 checkout-compare.py --ah /tmp/ah-order.json --picnic /tmp/picnic-cart.json
```

Use `--format json` when the result must be parsed by another agent/tool.

### 7) Verify

- AH cart: `appie-cli order`
- AH list: `appie-cli shopping-list`
- Picnic: `cart`
- Confirm quantities and total estimates with user before final checkout

## PATH

Ensure Go and appie-cli are available:

```bash
export PATH=$HOME/.local/go/bin:$HOME/go/bin:$PATH
```

## API Reference (appie-cli)

| Command | What it does | Auth needed? |
|---------|-------------|--------------|
| `search <query> [limit]` | Search products | No |
| `product <id>` | Product details | No |
| `bonus-products [limit]` | Current bonus products | No |
| `order` | View active AH order cart | Yes |
| `order-summary` | View active AH order totals | Yes |
| `add-to-order <id> [qty]` | Add product to active AH order cart | Yes |
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

- `config.json` - behavior flags and store overrides (copy from `config-template.json`)
- `weekly-basics.json` - recurring grocery items with AH product IDs
- `product-cache.json` - cached product IDs for faster matching
- `checkout-compare.py` - compare AH and Picnic cart totals for checkout decision
- `.appie.json` - AH auth tokens (auto-created on login, never commit)

## Important Rules

- Never mutate AH cart/list or Picnic cart without explicit user approval
- Prefer exact product matches; ask when matching confidence is low
- For AH, always factor bonus information into pricing explanation
- Keep calculations transparent: show assumptions and chosen package sizes
