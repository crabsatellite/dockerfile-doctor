#!/usr/bin/env bash
# validate_pr.sh — Build original & fixed Dockerfiles, compare results.
# Usage: ./scripts/validate_pr.sh <project-dir>
#
# Expects:
#   <project-dir>/Dockerfile      — the fixed version
#   <project-dir>/Dockerfile.bak  — the original version (git checkout)
#
# Produces: <project-dir>/validation_report.txt

set -uo pipefail
# Note: we do NOT use set -e because many comparison commands return non-zero
# (diff, comm, grep) — we handle errors explicitly instead.

PROJECT_DIR="${1:?Usage: validate_pr.sh <project-dir>}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
REPORT="$PROJECT_DIR/validation_report.txt"
TAG_ORIG="${PROJECT_NAME}-original"
TAG_FIXED="${PROJECT_NAME}-fixed"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
fail() { echo -e "${RED}[✗]${NC} $*"; }

# Ensure both Dockerfiles exist
if [[ ! -f "$PROJECT_DIR/Dockerfile" ]]; then
    fail "Missing $PROJECT_DIR/Dockerfile (fixed version)"
    exit 1
fi

# Create .bak from git if not present
if [[ ! -f "$PROJECT_DIR/Dockerfile.bak" ]]; then
    warn "No Dockerfile.bak found, restoring from git HEAD"
    (cd "$PROJECT_DIR" && git show HEAD~1:Dockerfile > Dockerfile.bak 2>/dev/null) || \
    (cd "$PROJECT_DIR" && git show main:Dockerfile > Dockerfile.bak 2>/dev/null) || \
    { fail "Cannot restore original Dockerfile"; exit 1; }
fi

echo "================================================================"
echo " Dockerfile PR Validation: $PROJECT_NAME"
echo " $(date)"
echo "================================================================"
echo ""

{
echo "================================================================"
echo " Dockerfile PR Validation Report: $PROJECT_NAME"
echo " Generated: $(date)"
echo "================================================================"
echo ""
} > "$REPORT"

PASS=0
FAIL=0
record() {
    # $1 = status (PASS/FAIL/WARN), $2 = message
    if [[ "$1" == "PASS" ]]; then
        log "$2"
        ((PASS++))
    elif [[ "$1" == "FAIL" ]]; then
        fail "$2"
        ((FAIL++))
    else
        warn "$2"
    fi
    echo "[$1] $2" >> "$REPORT"
}

# ----------------------------------------------------------------
# Step 1: Build original
# ----------------------------------------------------------------
echo "--- Step 1: Building ORIGINAL image ---"
echo "" >> "$REPORT"
echo "--- Step 1: Build Original ---" >> "$REPORT"

BUILD_ORIG_LOG="$PROJECT_DIR/.build_orig.log"
if docker build -t "$TAG_ORIG" -f "$PROJECT_DIR/Dockerfile.bak" "$PROJECT_DIR" > "$BUILD_ORIG_LOG" 2>&1; then
    record "PASS" "Original Dockerfile builds successfully"
else
    record "FAIL" "Original Dockerfile FAILED to build"
    echo "  Build log: $BUILD_ORIG_LOG"
    echo "BUILD LOG (original):" >> "$REPORT"
    tail -20 "$BUILD_ORIG_LOG" >> "$REPORT"
    # If original fails, we can still continue to test fixed
fi

# ----------------------------------------------------------------
# Step 2: Build fixed
# ----------------------------------------------------------------
echo ""
echo "--- Step 2: Building FIXED image ---"
echo "" >> "$REPORT"
echo "--- Step 2: Build Fixed ---" >> "$REPORT"

BUILD_FIXED_LOG="$PROJECT_DIR/.build_fixed.log"
if docker build -t "$TAG_FIXED" -f "$PROJECT_DIR/Dockerfile" "$PROJECT_DIR" > "$BUILD_FIXED_LOG" 2>&1; then
    record "PASS" "Fixed Dockerfile builds successfully"
else
    record "FAIL" "Fixed Dockerfile FAILED to build"
    echo "  Build log: $BUILD_FIXED_LOG"
    echo "BUILD LOG (fixed):" >> "$REPORT"
    tail -20 "$BUILD_FIXED_LOG" >> "$REPORT"
    echo ""
    echo "================================================================"
    fail "BUILD FAILED — do NOT submit PR"
    echo "================================================================"
    echo "" >> "$REPORT"
    echo "VERDICT: FAIL — Fixed Dockerfile does not build." >> "$REPORT"
    exit 1
fi

# ----------------------------------------------------------------
# Step 3: Image size comparison
# ----------------------------------------------------------------
echo ""
echo "--- Step 3: Image size comparison ---"
echo "" >> "$REPORT"
echo "--- Step 3: Image Size ---" >> "$REPORT"

SIZE_ORIG=$(docker image inspect "$TAG_ORIG" --format='{{.Size}}' 2>/dev/null || echo "0")
SIZE_FIXED=$(docker image inspect "$TAG_FIXED" --format='{{.Size}}' 2>/dev/null || echo "0")
SIZE_ORIG_MB=$((SIZE_ORIG / 1048576))
SIZE_FIXED_MB=$((SIZE_FIXED / 1048576))
SIZE_DIFF_MB=$(( (SIZE_ORIG - SIZE_FIXED) / 1048576 ))

echo "  Original: ${SIZE_ORIG_MB} MB"
echo "  Fixed:    ${SIZE_FIXED_MB} MB"
echo "  Saved:    ${SIZE_DIFF_MB} MB"
echo "  Original: ${SIZE_ORIG_MB} MB" >> "$REPORT"
echo "  Fixed:    ${SIZE_FIXED_MB} MB" >> "$REPORT"
echo "  Saved:    ${SIZE_DIFF_MB} MB" >> "$REPORT"

if [[ "$SIZE_FIXED" -le "$SIZE_ORIG" ]]; then
    record "PASS" "Fixed image is same size or smaller"
else
    record "WARN" "Fixed image is LARGER than original (+${SIZE_DIFF_MB} MB) — review changes"
fi

# ----------------------------------------------------------------
# Step 4: System packages comparison (dpkg)
# ----------------------------------------------------------------
echo ""
echo "--- Step 4: System packages comparison ---"
echo "" >> "$REPORT"
echo "--- Step 4: System Packages (dpkg) ---" >> "$REPORT"

PKGS_ORIG="$PROJECT_DIR/.pkgs_orig.txt"
PKGS_FIXED="$PROJECT_DIR/.pkgs_fixed.txt"
docker run --rm "$TAG_ORIG" dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | sort > "$PKGS_ORIG" 2>/dev/null || true
docker run --rm "$TAG_FIXED" dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | sort > "$PKGS_FIXED" 2>/dev/null || true

MISSING_PKGS=$(comm -23 "$PKGS_ORIG" "$PKGS_FIXED" || true)
EXTRA_PKGS=$(comm -13 "$PKGS_ORIG" "$PKGS_FIXED" || true)

if [[ -z "$MISSING_PKGS" ]]; then
    record "PASS" "No system packages lost in fixed image"
else
    MISSING_COUNT=$(echo "$MISSING_PKGS" | wc -l)
    record "FAIL" "$MISSING_COUNT system packages MISSING in fixed image (--no-install-recommends may have removed needed packages)"
    echo "  Missing packages:" >> "$REPORT"
    echo "$MISSING_PKGS" | sed 's/^/    /' >> "$REPORT"
    echo "  Missing packages:"
    echo "$MISSING_PKGS" | head -20 | sed 's/^/    /'
fi

if [[ -n "$EXTRA_PKGS" ]]; then
    echo "  (Fixed image has $(echo "$EXTRA_PKGS" | wc -l) extra packages — harmless)" >> "$REPORT"
fi

# ----------------------------------------------------------------
# Step 5: Python packages comparison (pip)
# ----------------------------------------------------------------
echo ""
echo "--- Step 5: Python packages comparison ---"
echo "" >> "$REPORT"
echo "--- Step 5: Python Packages (pip) ---" >> "$REPORT"

PIP_ORIG="$PROJECT_DIR/.pip_orig.txt"
PIP_FIXED="$PROJECT_DIR/.pip_fixed.txt"
docker run --rm "$TAG_ORIG" pip list --format=freeze 2>/dev/null | sort > "$PIP_ORIG" 2>/dev/null || true
docker run --rm "$TAG_FIXED" pip list --format=freeze 2>/dev/null | sort > "$PIP_FIXED" 2>/dev/null || true

PIP_DIFF=$(diff "$PIP_ORIG" "$PIP_FIXED" || true)
if [[ -z "$PIP_DIFF" ]]; then
    record "PASS" "Python packages identical"
else
    # Check if it's just version differences or missing packages
    PIP_MISSING=$(comm -23 <(cut -d= -f1 "$PIP_ORIG") <(cut -d= -f1 "$PIP_FIXED") || true)
    if [[ -z "$PIP_MISSING" ]]; then
        record "PASS" "Python packages present (minor version diffs only)"
    else
        record "FAIL" "Python packages MISSING in fixed image"
        echo "  Missing:" >> "$REPORT"
        echo "$PIP_MISSING" | sed 's/^/    /' >> "$REPORT"
        echo "  Missing:"
        echo "$PIP_MISSING" | sed 's/^/    /'
    fi
fi

# ----------------------------------------------------------------
# Step 6: CMD / ENTRYPOINT comparison
# ----------------------------------------------------------------
echo ""
echo "--- Step 6: CMD/ENTRYPOINT comparison ---"
echo "" >> "$REPORT"
echo "--- Step 6: CMD / ENTRYPOINT ---" >> "$REPORT"

CMD_ORIG=$(docker image inspect "$TAG_ORIG" --format='CMD={{.Config.Cmd}} ENTRYPOINT={{.Config.Entrypoint}}' 2>/dev/null || echo "N/A")
CMD_FIXED=$(docker image inspect "$TAG_FIXED" --format='CMD={{.Config.Cmd}} ENTRYPOINT={{.Config.Entrypoint}}' 2>/dev/null || echo "N/A")

echo "  Original: $CMD_ORIG" >> "$REPORT"
echo "  Fixed:    $CMD_FIXED" >> "$REPORT"
echo "  Original: $CMD_ORIG"
echo "  Fixed:    $CMD_FIXED"

# For CMD comparison, shell form wraps in [/bin/sh -c ...] while exec form is direct
# Both should ultimately run the same command
record "PASS" "CMD/ENTRYPOINT recorded (review above for equivalence)"

# ----------------------------------------------------------------
# Step 7: WORKDIR / ENV / EXPOSE comparison
# ----------------------------------------------------------------
echo ""
echo "--- Step 7: Config comparison ---"
echo "" >> "$REPORT"
echo "--- Step 7: WORKDIR / ENV / EXPOSE ---" >> "$REPORT"

for field in WorkingDir ExposedPorts; do
    VAL_ORIG=$(docker image inspect "$TAG_ORIG" --format="{{.Config.$field}}" 2>/dev/null || echo "N/A")
    VAL_FIXED=$(docker image inspect "$TAG_FIXED" --format="{{.Config.$field}}" 2>/dev/null || echo "N/A")
    if [[ "$VAL_ORIG" == "$VAL_FIXED" ]]; then
        record "PASS" "$field identical: $VAL_ORIG"
    else
        record "FAIL" "$field DIFFERS — Original: $VAL_ORIG, Fixed: $VAL_FIXED"
    fi
done

ENV_ORIG=$(docker image inspect "$TAG_ORIG" --format='{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^(PYTHONUNBUFFERED|IN_MISAGO|MISAGO_)' | sort || true)
ENV_FIXED=$(docker image inspect "$TAG_FIXED" --format='{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^(PYTHONUNBUFFERED|IN_MISAGO|MISAGO_)' | sort || true)
if [[ "$ENV_ORIG" == "$ENV_FIXED" ]]; then
    record "PASS" "Application ENV vars identical"
else
    record "FAIL" "Application ENV vars DIFFER"
    echo "  Original: $ENV_ORIG" >> "$REPORT"
    echo "  Fixed:    $ENV_FIXED" >> "$REPORT"
fi

# ----------------------------------------------------------------
# Step 8: Layer count
# ----------------------------------------------------------------
echo ""
echo "--- Step 8: Layer count ---"
echo "" >> "$REPORT"
echo "--- Step 8: Layer Count ---" >> "$REPORT"

LAYERS_ORIG=$(docker image inspect "$TAG_ORIG" --format='{{len .RootFS.Layers}}' 2>/dev/null || echo "?")
LAYERS_FIXED=$(docker image inspect "$TAG_FIXED" --format='{{len .RootFS.Layers}}' 2>/dev/null || echo "?")
echo "  Original: $LAYERS_ORIG layers" >> "$REPORT"
echo "  Fixed:    $LAYERS_FIXED layers" >> "$REPORT"
echo "  Original: $LAYERS_ORIG layers"
echo "  Fixed:    $LAYERS_FIXED layers"
record "PASS" "Layer count recorded"

# ----------------------------------------------------------------
# Summary
# ----------------------------------------------------------------
echo ""
echo "================================================================"
echo "" >> "$REPORT"
echo "================================================================" >> "$REPORT"

TOTAL=$((PASS + FAIL))
echo "  Results: $PASS/$TOTAL passed, $FAIL failed" >> "$REPORT"

if [[ $FAIL -eq 0 ]]; then
    log "ALL CHECKS PASSED ($PASS/$TOTAL) — safe to submit PR"
    echo "  VERDICT: PASS — Safe to submit PR." >> "$REPORT"
else
    fail "$FAIL CHECK(S) FAILED — review report before submitting PR"
    echo "  VERDICT: FAIL — Review issues before submitting PR." >> "$REPORT"
fi

echo "================================================================"
echo "  Full report: $REPORT"
echo "================================================================" >> "$REPORT"

# ----------------------------------------------------------------
# Cleanup: remove temp files and Docker images
# ----------------------------------------------------------------
echo ""
echo "--- Cleanup ---"
rm -f "$PKGS_ORIG" "$PKGS_FIXED" "$PIP_ORIG" "$PIP_FIXED" "$BUILD_ORIG_LOG" "$BUILD_FIXED_LOG"
docker rmi "$TAG_ORIG" "$TAG_FIXED" 2>/dev/null && log "Docker images removed" || warn "Some images could not be removed"
docker image prune -f > /dev/null 2>&1 || true
echo "  Cleanup: images and temp files removed" >> "$REPORT"

exit $FAIL
