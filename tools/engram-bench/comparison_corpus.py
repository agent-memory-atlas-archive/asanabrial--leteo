"""The held-out corpus the Engram comparison is measured on.

This is deliberately a different corpus from the one the ratchet gates on
(`corpus.py`). A benchmark that is also the tuning set cannot tell overfitting
from an improvement: every query here was written for the comparison, none of
them raises or lowers a floor in `floors.json`, and the ratchet never asks them.
`a_commit_does_not_change_the_comparison_corpus_with_the_search_it_scores` in
`tests/repository_guards.rs` refuses a commit that edits this file together with
`src/store/search*` or `src/store/semantic*`, so a ranking change cannot be
tuned against the corpus that is supposed to measure it.

The queries are neutral on purpose: most of them share a distinctive word with
the memory they should find, so a plain keyword match can answer them, and the
relaxed stages Leteo adds for paraphrases and fragments are not the only way
through. That is the opposite of the ratchet's corpus, whose paraphrases avoid
the target's words by design. The queries are still synthetic and were written
knowing how both engines search, which the page's caveats state.

Deterministic: a fixed seed, no network.
"""
import random

A, B = "alpha-api", "beta-web"


def T(key, project, typ, title, content, queries, topic=None):
    return dict(key=key, project=project, type=typ, title=title, content=content, topic=topic, queries=queries)


FILLER = (" The change was reviewed, the runbook was updated with the numbers, and a regression "
          "test was added so a later refactor cannot undo it quietly. Rollback is a single revert "
          "and no data migration is involved.")

TARGETS = [
    T("keyset", A, "decision", "Keyset pagination for the orders list",
      "Offset pagination re-read the whole table for deep pages. Orders now page by a (created_at, id) keyset cursor, so page N costs the same as page 1." + FILLER,
      [("multiword", "keyset pagination orders cursor"), ("longnl", "how do we page through a long list of orders without slowing down near the end")]),
    T("retry", A, "pattern", "Retries use exponential backoff with jitter",
      "Clients retry a failed call with exponential backoff, a 200 ms base, a 30 s cap and full jitter. A circuit breaker opens after ten consecutive failures.",
      [("multiword", "exponential backoff jitter retries"), ("short", "backoff"), ("typo", "exponetial backof jitter")]),
    T("uuid7", A, "decision", "New primary keys are UUIDv7",
      "Sequential integer ids leaked row counts and clustered badly on insert. New tables use UUIDv7, which is time-ordered, so index locality is preserved.",
      [("short", "uuidv7"), ("multiword", "uuidv7 primary key time ordered")]),
    T("idemkey", A, "pattern", "Mutating requests carry an Idempotency-Key",
      "A retried request must not do its work twice. Every POST and PATCH accepts an Idempotency-Key header and stores the first response for 24 hours.",
      [("multiword", "idempotency key mutating request header"), ("longnl", "how do we stop a retried request from doing the work twice")]),
    T("deadline", A, "bugfix", "Downstream calls had no deadline",
      "Root cause: context.Background() was passed to every downstream client, so a slow dependency blocked the caller forever. Each outbound call now gets a 2 s context.WithTimeout.",
      [("multiword", "downstream deadline context timeout"), ("longnl", "why did requests pile up when a dependency got slow"), ("paraphrase", "what happens when a downstream service never answers")]),
    T("auditlog", A, "decision", "The audit log is append-only",
      "Security-relevant writes append to an audit_log table with actor, action, target and timestamp. The table carries no update or delete grant.",
      [("multiword", "audit log append only actor action"), ("short", "audit_log")]),
    T("tokenbucket", A, "decision", "Rate limiting is a token bucket per API key",
      "A Lua script refills a token bucket atomically: 100 request burst and 10/s sustained per API key, keyed by the hash of the key.",
      [("multiword", "token bucket rate limit api key"), ("partial", "bucke"), ("typo", "token buckt rate limit")]),
    T("migrations", A, "pattern", "Migrations are append-only and timestamp-named",
      "A migration that has shipped is never edited. Each change is a new file named 20240101T120000_description.sql, and CI checks the applied list.",
      [("multiword", "append only migration timestamp name"), ("paraphrase", "can I change a migration that already ran")]),
    T("slog", A, "pattern", "Logs are structured JSON with a request id",
      "Handlers log through slog as JSON. Middleware injects request_id and user_id, and no handler calls fmt.Printf.",
      [("multiword", "structured json logs request id"), ("short", "slog")]),
    T("cors", A, "bugfix", "CORS preflight failed behind the auth middleware",
      "OPTIONS requests reached the auth middleware and got a 401 before the CORS headers were written. CORS middleware now runs first.",
      [("multiword", "cors preflight options auth middleware"), ("longnl", "why did the browser block the request with a preflight error")]),
    T("nplus1", A, "bugfix", "N+1 queries in the order history endpoint",
      "Line items were loaded per order in a loop. One query with ANY($1) and grouping in the app cut p95 from 900 ms to 60 ms.",
      [("multiword", "n+1 queries order history loop"), ("partial", "N+1")]),
    T("grpcpool", A, "bugfix", "The gRPC client leaked connections on reconnect",
      "Each reconnect built a new ClientConn and never closed the old one. The pool now closes on error and reuses a single connection.",
      [("multiword", "grpc reconnect connection leak pool"), ("typo", "grpc conection leek")]),
    T("featureflags", A, "decision", "Feature flags are evaluated server-side",
      "Client-side flags leaked unreleased feature names into the bundle. Flags are now evaluated in the API and only booleans reach the client.",
      [("multiword", "feature flags evaluated server side"), ("paraphrase", "where are feature toggles decided")]),
    T("es_factura", A, "bugfix", "Corregido: facturas con la fecha de un día antes",
      "Causa raíz: la fecha se calculaba en UTC y se formateaba en hora local. Ahora se calcula en la zona horaria IANA de la cuenta.",
      [("spanish", "facturas con fecha equivocada por zona horaria")]),
    T("es_indice", A, "discovery", "Descubrimiento: índice parcial para pedidos activos",
      "El 90% de las filas están archivadas. Un índice parcial WHERE archived = false bajó el tamaño del índice de 3 GB a 280 MB.",
      [("spanish", "índice parcial para pedidos activos"), ("spanish", "indice parcial pedidos archivados")]),
    T("hydration", B, "bugfix", "Hydration mismatch from dates rendered in SSR",
      "The server rendered dates in UTC and the browser in the local zone, so React threw a hydration mismatch and re-rendered the tree. Dates now render client-only inside a useEffect gate.",
      [("multiword", "hydration mismatch dates ssr useeffect"), ("longnl", "why did react complain that the server html differs from the client")]),
    T("zustand", B, "decision", "Client state is Zustand, server state is TanStack Query",
      "Redux boilerplate slowed every feature. Per-domain Zustand stores hold UI state, and server data stays in TanStack Query.",
      [("multiword", "zustand tanstack query client state"), ("short", "zustand"), ("paraphrase", "which libraries hold client and server state")]),
    T("moment", B, "discovery", "Moment.js added 280 KB to the bundle",
      "The analyzer showed moment with every locale in the main chunk. date-fns with tree-shaken imports cut the bundle 31%.",
      [("multiword", "bundle size moment date-fns analyzer"), ("partial", "analyz")]),
    T("aria", B, "pattern", "Icon-only buttons need an aria-label",
      "Screen readers announced icon buttons as just button. The lint rule jsx-a11y/control-has-associated-label enforces an aria-label.",
      [("multiword", "aria-label icon button screen reader"), ("short", "aria")]),
    T("csp", B, "decision", "Content Security Policy uses per-request nonces",
      "Inline scripts run only with a per-request nonce. Third-party analytics load through a proxied domain so the policy stays strict.",
      [("multiword", "content security policy nonce inline script"), ("short", "csp")]),
    T("usememo", B, "bugfix", "Infinite re-render from an unstable effect dependency",
      "useEffect depended on an object literal recreated on every render and set state each time. The filter object is memoized with useMemo.",
      [("multiword", "infinite re-render useeffect usememo"), ("typo", "infinte rerender useefect")]),
    T("serviceworker", B, "bugfix", "The service worker served a stale app shell",
      "index.html was cached cache-first, so users kept old bundle hashes and got 404s on chunks. index.html is network-first and the worker calls skipWaiting.",
      [("multiword", "service worker stale cache skipwaiting"), ("longnl", "why were users stuck on the old version after a deploy")]),
    T("zodforms", B, "pattern", "Forms use react-hook-form with a zod schema",
      "Validation rules live in a zod schema shared with the API types, and react-hook-form holds the state. Large forms avoid controlled inputs.",
      [("multiword", "react-hook-form zod schema validation"), ("short", "zod")]),
    T("fonts", B, "bugfix", "Flash of invisible text from self-hosted fonts",
      "Fonts were declared without font-display, so text stayed invisible for up to 3 s on a slow network. font-display: swap and preloading the two main weights fixed it.",
      [("multiword", "font-display swap invisible text preload"), ("short", "foit")]),
    T("es_acentos", B, "bugfix", "Corregido: el registro perdía los acentos",
      "Los nombres con tildes llegaban rotos porque el proxy reescribía el Content-Type sin charset. Se fuerza charset=utf-8 en el proxy y en el fetch.",
      [("spanish", "acentos perdidos en el registro")]),
    T("design_tokens", B, "pattern", "Design tokens are CSS variables",
      "Colours are tokens on :root and are redefined under prefers-color-scheme: dark. Components never hard-code a hex value.",
      [("multiword", "design tokens css variables prefers-color-scheme"), ("partial", "prefers")]),
    T("avif", B, "decision", "Images are served as AVIF with a WebP fallback",
      "The image CDN negotiates on the Accept header and serves AVIF, falling back to WebP for older browsers.",
      [("multiword", "avif webp cdn accept header"), ("short", "avif")]),
]

SERVICES = ["billing", "inventory", "checkout", "notifications", "search", "catalog", "shipping", "accounts"]
TECH = ["Postgres", "Redis", "Kafka", "gRPC", "S3", "Kubernetes", "Nginx", "React", "TypeScript", "Go"]
VERBS = ["Refactored", "Documented", "Investigated", "Tuned", "Cleaned up", "Split", "Renamed", "Upgraded"]
OBJS = ["the retry policy", "the config loader", "error wrapping", "the health endpoint", "the batch job",
        "the metrics labels", "the deploy pipeline", "test fixtures", "the API client", "the CSV export",
        "the cache keys", "the webhook handler", "the session store", "the queue consumer"]
TYPES = ["decision", "bugfix", "discovery", "pattern", "config"]


def distractors(n=64, seed=11):
    """Fillers that share vocabulary, so a bag-of-words match is not enough."""
    r = random.Random(seed)
    out = []
    for i in range(n):
        proj = A if i % 2 == 0 else B
        s, t, v, o = r.choice(SERVICES), r.choice(TECH), r.choice(VERBS), r.choice(OBJS)
        title = f"{v} {o} in {s}"
        body = (f"{v} {o} in the {s} service that talks to {t}. The previous approach was hard to test and "
                f"produced noisy logs during deploys. The result is simpler code with the same behaviour. "
                f"Request latency and error rate were unchanged. Ticket {2000 + i}.")
        out.append(dict(key=f"c{i}", project=proj, type=r.choice(TYPES), title=title, content=body, topic=None, queries=[]))
    return out


def corpus():
    return TARGETS + distractors()


def queries():
    qs = []
    for t in TARGETS:
        for kind, q in t["queries"]:
            qs.append(dict(kind=kind, q=q, target=t["key"], project=t["project"]))
    return qs


# Questions no memory here answers. They are about people, offices and money, and
# each names its project so it is asked of a store that really holds nothing for
# it. Not in `queries()`: they have no target to rank and never enter the
# answerable MRR.
NO_ANSWER = [
    (A, "what is our parental leave policy"),
    (A, "who approves travel expenses"),
    (A, "how many vacation days do we get"),
    (A, "what is the guest wifi password"),
    (A, "when is the next company all-hands"),
    (A, "how do I request a new laptop"),
    (A, "which health insurance provider do we use"),
    (A, "how do I book a meeting room"),
    (B, "cuál es la política de vacaciones"),
    (B, "cómo pido un portátil nuevo"),
    (B, "cuándo es la cena de empresa"),
    (B, "qué proveedor de nóminas usamos"),
    (B, "cómo se reserva una sala de reuniones"),
    (B, "cuántos días de teletrabajo hay"),
    (B, "quién aprueba los gastos de viaje"),
    (B, "cuál es el horario de verano"),
]


def no_answer():
    return [dict(kind="no_answer", q=q, project=p) for p, q in NO_ANSWER]


if __name__ == "__main__":
    from collections import Counter

    c = corpus()
    q = queries()
    print(len(c), "memories;", len(q), "queries", Counter(x["kind"] for x in q))
