#!/usr/bin/env bash
# Regression test for scripts/lib/ingress-nginx.sh: every ensure_ingress_nginx
# run (fresh install and --reuse-values upgrade) must turn HTTP/2 off on the
# shared controller, which bundles NGINX2Root-affected nginx 1.27.1.
# helm and kubectl are stubbed; no cluster is needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat >"$TMP/bin/helm" <<'STUB'
#!/usr/bin/env bash
echo "helm $*" >>"$STUB_LOG"
if [ "$1" = status ]; then [ "${STUB_RELEASE_EXISTS:-0}" = 1 ]; exit; fi
exit 0
STUB
printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/bin/kubectl"
chmod +x "$TMP/bin/helm" "$TMP/bin/kubectl"

failures=0
run_case() {  # <name> <release-exists 0|1> <expected use-http2> [env...]
  local name="$1" exists="$2" want="$3"; shift 3
  local log="$TMP/$name.log"
  : >"$log"
  env "$@" PATH="$TMP/bin:$PATH" STUB_LOG="$log" STUB_RELEASE_EXISTS="$exists" \
    bash -c "source '$ROOT/scripts/lib/ingress-nginx.sh'; ensure_ingress_nginx" >/dev/null 2>&1
  local install
  install="$(grep '^helm upgrade --install ingress-nginx ' "$log" || true)"
  if [ -z "$install" ]; then
    echo "FAIL $name: no helm upgrade --install"; failures=$((failures + 1)); return
  fi
  if grep -q -- "--set-string controller.config.use-http2=${want}\( \|$\)" <<<"$install"; then
    echo "ok   $name: use-http2=${want}"
  else
    echo "FAIL $name: expected --set-string controller.config.use-http2=${want} in: $install"
    failures=$((failures + 1))
  fi
  if [ "$exists" = 1 ] && ! grep -q -- '--reuse-values' <<<"$install"; then
    echo "FAIL $name: existing release upgraded without --reuse-values"; failures=$((failures + 1))
  fi
}

run_case fresh-install 0 false
run_case upgrade-existing-release 1 false
run_case explicit-opt-in 1 true INGRESS_USE_HTTP2=true

# Any other script that helm-upgrades the shared controller must restate
# use-http2 too: --reuse-values falls back to the last deployed revision.
while IFS= read -r f; do
  if grep -q 'controller\.config\.use-http2=' "$f"; then
    echo "ok   ${f#"$ROOT"/} sets use-http2"
  else
    echo "FAIL ${f#"$ROOT"/} upgrades ingress-nginx without controller.config.use-http2"
    failures=$((failures + 1))
  fi
done < <(grep -rlE 'helm upgrade.*(ingress-nginx/ingress-nginx|INGRESS_RELEASE)' "$ROOT/scripts" "$ROOT/demo-platform" 2>/dev/null | grep -v /test-ingress-nginx.sh)

[ "$failures" -eq 0 ] && echo "OK ingress-nginx.sh keeps HTTP/2 off by default"
exit "$failures"
