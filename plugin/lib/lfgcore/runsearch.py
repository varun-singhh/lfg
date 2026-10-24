"""Search a project's runs by meaning: vector search over what each run is about (its brief, tasks, notes, review
and fix reports), all on this computer.

With a local Ollama embedding model (`search.embed_model`, default nomic-embed-text) each run is embedded once and
kept in ~/.lfg/repos/<repo-id>/run-index.json until its files change; the query is embedded the same way and runs
are ranked by cosine similarity. Without one, the same ranking runs on TF-IDF vectors built here, so search works
from the start and gets better once the model is installed. Only a local Ollama is ever called (settings refuses
any other URL). Author: Varun Singh."""
import json
import math
import os
import re
from collections import Counter

from . import common as C

DEFAULT_MODEL = "nomic-embed-text"
DOC_CHARS = 6000
WORD = re.compile(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]")
STOP = set("the a an and or of to in on for is are was be it this that with as by at from we you not no but if "
           "into than then so do does did can will just its their our has have had".split())


def model():
    return ((C.config().get("search") or {}).get("embed_model") or DEFAULT_MODEL).strip()


def _doc(d):
    """What a run is about, as text: names, branch, PR and issue, brief, tasks, notes, review and fix reports."""
    meta = C.read_json(os.path.join(d, "run.json"), {}) or {}
    parts = [os.path.basename(d), meta.get("slug") or "", meta.get("branch") or "", meta.get("issue") or "",
             "PR %s" % meta["pr"] if meta.get("pr") else ""]
    for name in ("01-brief.md", "02-design.md", "fix-report.md"):
        parts.append(C.read_text(os.path.join(d, name))[:2500])
    tasks = C.read_json(os.path.join(d, "tasks.json"), None)
    tl = tasks.get("tasks", []) if isinstance(tasks, dict) else tasks if isinstance(tasks, list) else []
    parts += [" ".join(str(t.get(k) or "") for k in ("title", "description", "id")) for t in tl[:40]
              if isinstance(t, dict)]
    rv = C.read_json(os.path.join(d, "06-review.json"), None)
    if isinstance(rv, dict):
        parts.append(json.dumps(rv.get("summary") or "")[:1500])
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if re.match(r"^03-(build|fix)-.*\.md$", f):
            parts.append(C.read_text(os.path.join(d, f))[:800])
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()[:DOC_CHARS]


def _sig(d):
    """Changes whenever any of the run's files change, so its vector is made again."""
    try:
        return max(os.path.getmtime(os.path.join(r, f)) for r, _ds, fs in os.walk(d) for f in fs)
    except ValueError:
        return 0


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da, db = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


# ---------------------------------------------------------------- Ollama embeddings

def available():
    """Is the embedding model installed in the local Ollama? (name, True/False); False when Ollama isn't running."""
    from . import settings as S
    try:
        names = [m.get("name", "") for m in S._ollama_json("/api/tags").get("models") or []]
    except Exception:
        return model(), False
    m = model()
    return m, any(n == m or n.split(":")[0] == m.split(":")[0] for n in names)


def _embed(texts, kind):
    """Vectors for `texts` from the local Ollama; nomic-style models want a task prefix."""
    from . import settings as S
    m = model()
    pre = ("search_query: " if kind == "query" else "search_document: ") if "nomic" in m else ""
    out = S._ollama_json("/api/embed", {"model": m, "input": [pre + t for t in texts]}, timeout=120)
    vecs = out.get("embeddings") or []
    if len(vecs) != len(texts):
        raise RuntimeError("the embedding model gave %d vectors for %d texts" % (len(vecs), len(texts)))
    return vecs


def _index(rid, dirs):
    """{run: vector} with Ollama, made again only for runs whose files changed."""
    p = C.lfg_path("repos", rid, "run-index.json")
    idx = C.read_json(p, None)
    m = model()
    if not isinstance(idx, dict) or idx.get("model") != m:
        idx = {"model": m, "runs": {}}
    runs, todo = idx["runs"], []
    for d in dirs:
        name, sig = os.path.basename(d), _sig(d)
        if (runs.get(name) or {}).get("sig") != sig:
            todo.append((name, sig, _doc(d)))
    for i in range(0, len(todo), 16):
        chunk = todo[i:i + 16]
        for (name, sig, _t), vec in zip(chunk, _embed([t or name for _n, _s, t in chunk], "doc")):
            runs[name] = {"sig": sig, "vec": vec}
    keep = {os.path.basename(d) for d in dirs}
    idx["runs"] = {k: v for k, v in runs.items() if k in keep}
    if todo or len(idx["runs"]) != len(runs):
        C.ensure_dir(os.path.dirname(p))
        C.write_json(p, idx)
    return idx["runs"]


# ---------------------------------------------------------------- TF-IDF vectors (no model needed)

def _tokens(text):
    return [w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


def _tfidf_rank(docs, query):
    """Cosine similarity of the query to each doc on TF-IDF vectors, sparse, built here."""
    toks = {k: Counter(_tokens(v)) for k, v in docs.items()}
    n = len(toks) or 1
    df = Counter(w for c in toks.values() for w in c)
    idf = {w: math.log((n + 1) / (f + 1)) + 1 for w, f in df.items()}

    def vec(c):
        v = {w: (1 + math.log(f)) * idf.get(w, math.log(n + 1) + 1) for w, f in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {w: x / norm for w, x in v.items()}
    q = vec(Counter(_tokens(query)))
    return {k: sum(q.get(w, 0) * x for w, x in vec(c).items()) for k, c in toks.items()}


def search(rid, query, dirs, limit=30):
    """Runs most like `query`, best first: [{run, score}], and which engine ranked them."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:500]
    if not query or not dirs:
        return {"results": [], "engine": None}
    m, ok = available()
    if ok:
        try:
            vecs = _index(rid, dirs)
            q = _embed([query], "query")[0]
            scores = {k: _cos(q, v["vec"]) for k, v in vecs.items()}
            engine = "embeddings"
        except Exception:
            ok = False
    if not ok:
        scores = _tfidf_rank({os.path.basename(d): _doc(d) for d in dirs}, query)
        engine = "tfidf"
    floor = 0.2 if engine == "embeddings" else 0.01
    ranked = sorted(((k, s) for k, s in scores.items() if s >= floor), key=lambda x: -x[1])[:limit]
    return {"results": [{"run": k, "score": round(s, 3)} for k, s in ranked], "engine": engine, "model": m,
            "model_ready": ok}
