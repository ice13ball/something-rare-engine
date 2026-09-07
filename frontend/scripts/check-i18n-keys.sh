#!/usr/bin/env bash
# Compare top-level translation keys across locales.
# Flags missing keys in pl/fr/de relative to en (the schema).
# Exits 0 with warnings (not failures) so partial translations can ship.

set -u

FRONTEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCALES_DIR="$FRONTEND_DIR/public/locales"
NAMESPACES=(common panels legend enums tutorial)
LOCALES=(pl fr de)

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required. Install with: brew install jq"
  exit 1
fi

WARN_COUNT=0
for ns in "${NAMESPACES[@]}"; do
  EN_FILE="$LOCALES_DIR/en/$ns.json"
  if [[ ! -f "$EN_FILE" ]]; then
    echo "ERROR: $EN_FILE missing"
    exit 1
  fi
  EN_KEYS=$(jq -r 'paths(scalars) | join(".")' "$EN_FILE" | sort)

  for loc in "${LOCALES[@]}"; do
    LOC_FILE="$LOCALES_DIR/$loc/$ns.json"
    if [[ ! -f "$LOC_FILE" ]]; then
      echo "WARN: $LOC_FILE does not exist (skipping)"
      WARN_COUNT=$((WARN_COUNT + 1))
      continue
    fi
    LOC_KEYS=$(jq -r 'paths(scalars) | join(".")' "$LOC_FILE" | sort)

    MISSING=$(comm -23 <(echo "$EN_KEYS") <(echo "$LOC_KEYS"))
    EXTRA=$(comm -13 <(echo "$EN_KEYS") <(echo "$LOC_KEYS"))

    if [[ -n "$MISSING" ]]; then
      echo "WARN: $loc/$ns.json missing $(echo "$MISSING" | wc -l | tr -d ' ') keys vs en:"
      echo "$MISSING" | sed 's/^/  - /'
      WARN_COUNT=$((WARN_COUNT + 1))
    fi
    if [[ -n "$EXTRA" ]]; then
      echo "WARN: $loc/$ns.json has $(echo "$EXTRA" | wc -l | tr -d ' ') keys not in en:"
      echo "$EXTRA" | sed 's/^/  + /'
      WARN_COUNT=$((WARN_COUNT + 1))
    fi
  done
done

if [[ $WARN_COUNT -eq 0 ]]; then
  echo "OK: all locales have key parity with en."
fi
exit 0
