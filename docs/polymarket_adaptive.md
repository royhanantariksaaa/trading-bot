# Polymarket adaptive overlay

This adds a **Polymarket-native adaptive layer** on top of the paper MM loop.

What it watches each loop:
- best bid / ask and midpoint
- spread width as a probability percent
- top-of-book and 3-level depth imbalance
- weighted spread shape across the first 3 levels
- midpoint drift versus the prior loop
- liquidity quality score
- time-to-resolution when Gamma metadata is available

What it can change:
- `PM_BASE_SPREAD`
- `PM_EDGE_OFFSET`
- `PM_QUOTE_SIZE`
- `PM_MAX_INVENTORY`
- `PM_MAX_POSITION_NOTIONAL`
- `PM_INVENTORY_SKEW_PER_SHARE`

It does **not** change selection mode, token id, or paper/live mode. It also scales around your existing config instead of hard-replacing it with some Binance cosplay preset.

## Modes

- `PM_ADAPTIVE_MODE=off` → disabled
- `PM_ADAPTIVE_MODE=paper` → only active when `PM_PAPER_MODE=true`
- `PM_ADAPTIVE_MODE=on` → always active

## Presets

- `tight_balanced` — tighter book, healthy depth, near-neutral pressure
- `drift_follow` — midpoint drift plus supporting imbalance, but still bounded
- `imbalanced_defensive` — wide / thin / one-sided book, reduce size and inventory appetite
- `resolution_caution` — market close to resolution, get smaller and more defensive

## Paper-mode example

```powershell
$env:PM_PAPER_MODE="true"
$env:PM_ADAPTIVE_MODE="paper"
$env:PM_SELECTION_MODE="scan"
$env:PM_SELECTION_ROTATE_EVERY_LOOPS="0"
$env:PM_LOOPS="20"
python -m app.polymarket.main
```

## Reports

Each adaptive evaluation writes:
- text report: `data/market/polymarket_adaptive_report.txt`
- json report: `data/market/polymarket_adaptive_report.json`

The run log also appends the chosen adaptive preset in the `notes` column.
