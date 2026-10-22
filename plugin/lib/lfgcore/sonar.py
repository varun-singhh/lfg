"""`lfg sonar`: a local SonarQube to find and fix what SonarCloud would fail, before pushing.

Optional pack (`lfg add sonarqube`). SonarQube Community runs in Docker on 127.0.0.1:9000 (container
`lfg-sonarqube`, volumes `lfg-sonarqube-*`, all labelled `lfg=sonarqube` so LFG only ever removes its own). On setup
LFG changes the stock admin/admin login to a generated password and makes a scanner token, both kept in
~/.lfg/sonarqube/credentials.json (mode 600, never printed except by `lfg sonar login`).

`lfg sonar scan` copies what SonarCloud would see (git-tracked and new, never ignored or secret-looking files) to a
scratch folder and analyses it with SonarSource's npm scanner on the Mac's own Node (the Docker scanner image is
Intel-only and its Node crashes under emulation on Apple silicon; the npm scanner gets its Java runtime from the
local server, kept in ~/.lfg/sonarqube/home), honouring the repo's `.sonarcloud.properties` /
`sonar-project.properties`, waits for the result, and writes ~/.lfg/repos/<repo-id>/sonar.json: the quality gate,
every open issue and hotspot, and which of them sit on lines this branch changed (what SonarCloud's PR check
judges). `cloud()` reads SonarCloud's own verdict for a commit from its GitHub check run, read-only through gh.
Community edition has no branch analysis, so "on your change" comes from the git diff against the base. Author:
Varun Singh."""
import base64
import json
import os
import re
import secrets
import string
import time
import urllib.error
import urllib.parse
import urllib.request

from . import common as C

# Pinned (rule 9): SonarQube Community 26.10.0.133078 by digest; SonarSource's npm scanner by exact version.
SERVER_IMAGE = "sonarqube@sha256:0b3408443fb6a311253de27941b10977c9b977fd53be2265947bfe14161308b8"
SCANNER_PKG = "@sonar/scan@5.0.2"
NAME = "lfg-sonarqube"
LABEL = "lfg=sonarqube"
PORT = 9000
URL = "http://127.0.0.1:%d" % PORT
VOLUMES = ("data", "extensions", "logs")
PASS_THROUGH = re.compile(r"^sonar\.(sources|tests|exclusions|test\.inclusions|test\.exclusions|inclusions|"
                          r"cpd\.exclusions|coverage\.exclusions|issue\.ignore\.[\w.]+|javascript\.[\w.]+|"
                          r"typescript\.[\w.]+|sourceEncoding|python\.version|java\.binaries)$")


class Problem(RuntimeError):
    pass


def creds_path():
    return C.lfg_path("sonarqube", "credentials.json")


def creds():
    return C.read_json(creds_path(), None) or {}


def _docker(*args, timeout=600):
    return C.run(["docker", *args], timeout=timeout)


def _api(path, method="GET", data=None, auth=None, timeout=30):
    """SonarQube web API on 127.0.0.1. auth: (user, password) or a token."""
    req = urllib.request.Request(URL + path, method=method,
                                 data=urllib.parse.urlencode(data).encode() if data is not None else None)
    if auth:
        raw = ("%s:%s" % auth) if isinstance(auth, tuple) else (auth + ":")
        req.add_header("Authorization", "Basic " + base64.b64encode(raw.encode()).decode())
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def scanner_js():
    return C.lfg_path("sonarqube", "scanner", "node_modules", "@sonar", "scan", "bin", "sonar-scanner.js")


def install_scanner(log=print):
    """SonarSource's npm scanner, pinned, into ~/.lfg/sonarqube/scanner (never a repo), install scripts off."""
    if os.path.exists(scanner_js()):
        return
    if not (C.which("node") and C.which("npm")):
        raise Problem("Node.js is needed for the scanner: install it (brew install node) and re-run")
    log("    installing %s" % SCANNER_PKG)
    d = C.ensure_dir(C.lfg_path("sonarqube", "scanner"))
    cp = C.run(["npm", "install", "--prefix", d, "--no-save", "--ignore-scripts", "--no-audit", "--no-fund",
                SCANNER_PKG], timeout=600)
    if cp.returncode or not os.path.exists(scanner_js()):
        raise Problem("npm install %s failed: %s" % (SCANNER_PKG, (cp.stderr or cp.stdout).strip()[-300:]))


def server_state():
    """'up', 'starting', 'stopped' (container exists, not running) or 'missing'."""
    cp = _docker("inspect", "-f", "{{.State.Running}}", NAME, timeout=30)
    if cp.returncode:
        return "missing"
    if cp.stdout.strip() != "true":
        return "stopped"
    try:
        return "up" if _api("/api/system/status", timeout=5).get("status") == "UP" else "starting"
    except (urllib.error.URLError, OSError, ValueError):
        return "starting"


def privacy_env():
    """SonarQube's phone-home switches, from the `sonarqube.telemetry` setting (off by default: fully local)."""
    on = "true" if (C.config().get("sonarqube") or {}).get("telemetry") else "false"
    return {"SONAR_TELEMETRY_ENABLE": on, "SONAR_UPDATECENTER_ACTIVATE": on}


def privacy_applied():
    """True when the running container matches the setting, False when it needs a restart, None if no server."""
    cp = _docker("inspect", "-f", "{{json .Config.Env}}", NAME, timeout=30)
    if cp.returncode:
        return None
    try:
        env = dict(x.split("=", 1) for x in json.loads(cp.stdout or "[]") if "=" in x)
    except ValueError:
        return None
    return all(env.get(k, "true") == v for k, v in privacy_env().items())


def apply_privacy(log=print):
    """Recreate LFG's container with the current setting. Volumes (analyses, login) are kept."""
    if privacy_applied() is not False:
        return {"restarted": False}
    lab = _docker("inspect", "-f", "{{index .Config.Labels \"lfg\"}}", NAME, timeout=30)
    if lab.stdout.strip() != "sonarqube":
        raise Problem("the %s container wasn't made by LFG; not touching it" % NAME)
    _docker("rm", "-f", NAME, timeout=120)
    setup(log)
    return {"restarted": True}


def _password():
    """SonarQube wants 12+ characters with upper, lower, a digit and a symbol."""
    pool = string.ascii_letters + string.digits
    core = "".join(secrets.choice(pool) for _ in range(20))
    return core + secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase) + \
        secrets.choice(string.digits) + secrets.choice("-_.!")


def setup(log=print, wait_s=600):
    """Pull the pinned images, start the server on 127.0.0.1, and replace admin/admin with a generated password
    plus a scanner token. Safe to run again."""
    if not C.which("docker"):
        raise Problem("Docker isn't installed (the Ship check pack installs it)")
    if _docker("info", timeout=30).returncode:
        raise Problem("Docker isn't running: open Docker Desktop and try again")
    if _docker("image", "inspect", SERVER_IMAGE, timeout=30).returncode:
        log("    pulling SonarQube Community (about 1.1 GB)")
        cp = _docker("pull", SERVER_IMAGE, timeout=1800)
        if cp.returncode:
            raise Problem("docker pull failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    install_scanner(log)
    st = server_state()
    if st == "missing":
        log("    starting SonarQube on %s" % URL)
        args = ["run", "-d", "--name", NAME, "--label", LABEL, "--restart", "unless-stopped",
                "-p", "127.0.0.1:%d:9000" % PORT, "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true"]
        for k, v in privacy_env().items():
            args += ["-e", "%s=%s" % (k, v)]
        for v in VOLUMES:
            vol = "%s-%s" % (NAME, v)
            _docker("volume", "create", "--label", LABEL, vol, timeout=60)
            args += ["-v", "%s:/opt/sonarqube/%s" % (vol, v)]
        cp = _docker(*(args + [SERVER_IMAGE]), timeout=300)
        if cp.returncode:
            raise Problem("docker run failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    elif st == "stopped":
        _docker("start", NAME, timeout=120)
    end = time.time() + wait_s
    while server_state() != "up":
        if time.time() > end:
            raise Problem("SonarQube didn't come up within %ds; see `docker logs %s`" % (wait_s, NAME))
        time.sleep(5)
    c = creds()
    if not (c.get("password") and c.get("token")):
        password = c.get("password") or _password()
        if not c.get("password"):
            try:
                _api("/api/users/change_password", "POST",
                     {"login": "admin", "previousPassword": "admin", "password": password}, auth=("admin", "admin"))
            except urllib.error.HTTPError as e:
                raise Problem("couldn't replace the admin/admin login (%s); if you changed it yourself, put it in "
                              "%s as {\"user\": \"admin\", \"password\": \"...\"}" % (e.code, creds_path())) from None
        C.write_json(creds_path(), {"user": "admin", "password": password, "url": URL})
        tok = _api("/api/user_tokens/generate", "POST", {"name": "lfg-scanner-%d" % int(time.time()),
                                                         "type": "GLOBAL_ANALYSIS_TOKEN"},
                   auth=("admin", password))
        C.write_json(creds_path(), {"user": "admin", "password": password, "token": tok["token"], "url": URL})
        log("    admin login set (lfg sonar login shows it); scanner token made")
    os.chmod(creds_path(), 0o600)
    from . import claudecfg as CC
    if not CC.find(tag="sonarqube-server"):
        CC.cmd_done(["docker", "run", "--name", NAME], ["docker", "rm", "-f", NAME],
                    "local SonarQube server (Docker, 127.0.0.1:%d)" % PORT, "sonarqube", tag="sonarqube-server")
    return {"url": URL, "state": server_state()}


def stop():
    return _docker("stop", NAME, timeout=120).returncode == 0


def remove(volumes=False):
    """Remove LFG's SonarQube container (and, if asked, its data volumes). Only LFG-labelled resources."""
    cp = _docker("inspect", "-f", "{{index .Config.Labels \"lfg\"}}", NAME, timeout=30)
    if cp.returncode == 0 and cp.stdout.strip() == "sonarqube":
        _docker("rm", "-f", NAME, timeout=120)
    if volumes:
        for v in VOLUMES:
            vol = "%s-%s" % (NAME, v)
            lab = _docker("volume", "inspect", "-f", "{{index .Labels \"lfg\"}}", vol, timeout=30)
            if lab.returncode == 0 and lab.stdout.strip() == "sonarqube":
                _docker("volume", "rm", vol, timeout=60)
        try:
            os.remove(creds_path())
        except OSError:
            pass
    return {"removed": True, "volumes": volumes}


# ---------------------------------------------------------------- scanning

def _props(root):
    """sonar.* settings from the repo's own files, so the local scan looks at what SonarCloud looks at."""
    out = {}
    for f in (".sonarcloud.properties", "sonar-project.properties"):
        for line in C.read_text(os.path.join(root, f)).splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "!")) or "=" not in line:
                continue
            k, v = (x.strip() for x in line.split("=", 1))
            if PASS_THROUGH.match(k):
                out[k] = v
    return out


def stage(rid, root):
    """Copy what SonarCloud would see into a scratch folder: git-tracked files plus new files that aren't ignored,
    never anything that looks like a secret file (guard.is_secret_path) or is over 20 MB. The scanner only ever
    mounts this copy, so ignored files (.env, node_modules, graph output) can't reach it."""
    import shutil
    from . import guard
    dest = C.lfg_path("tmp", "sonar", rid)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, mode=0o700)
    cp = C.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, timeout=120)
    if cp.returncode:
        raise Problem("git ls-files failed: %s" % (cp.stderr or "").strip()[-200:])
    copied = skipped = 0
    for rel in sorted(set(x for x in cp.stdout.split("\0") if x)):
        src = os.path.join(root, rel)
        if rel.startswith("../") or guard.is_secret_path(src) or not os.path.isfile(src) or os.path.islink(src):
            skipped += 1
            continue
        if os.path.getsize(src) > 20 * 1024 * 1024:
            skipped += 1
            continue
        out = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copyfile(src, out)
        copied += 1
    return dest, copied, skipped


def project_key(rid):
    return "lfg_" + re.sub(r"[^A-Za-z0-9_.:-]", "_", re.sub(r"-[0-9a-f]{8}$", "", rid))


def _changed_lines(root, base):
    """{path: set(line)} of lines this branch added or changed against `base` (the merge-base)."""
    cp = C.run(["git", "diff", "--no-color", "-U0", base], cwd=root, timeout=300)
    out, path = {}, None
    for line in (cp.stdout or "").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m and m.group(2) != "0":
                start = int(m.group(1))
                out.setdefault(path, set()).update(range(start, start + int(m.group(2) or 1)))
    return out


def _base(root, base=None):
    if base:
        return C.run(["git", "merge-base", base, "HEAD"], cwd=root, timeout=60).stdout.strip() or base
    head = C.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root, timeout=30).stdout.strip()
    ref = head or "origin/main"
    return C.run(["git", "merge-base", ref, "HEAD"], cwd=root, timeout=60).stdout.strip()


def _paged(path, token, key):
    out, page = [], 1
    while True:
        res = _api("%s&p=%d&ps=500" % (path, page), auth=token, timeout=60)
        items = res.get(key) or []
        out += items
        total = (res.get("paging") or {}).get("total", res.get("total", len(out)))
        if not items or len(out) >= total or page >= 20:
            return out
        page += 1


def scan(rid, root, base=None, log=print, timeout_s=3600):
    """Analyse `root` (a checkout or worktree) and return/save the result."""
    if server_state() != "up":
        raise Problem("SonarQube isn't running: `lfg sonar setup` (or `lfg add sonarqube`)")
    c = creds()
    if not c.get("token"):
        raise Problem("no scanner token yet: run `lfg sonar setup`")
    key = project_key(rid)
    try:
        _api("/api/projects/create", "POST", {"project": key, "name": re.sub(r"-[0-9a-f]{8}$", "", rid)},
             auth=(c["user"], c["password"]))
    except urllib.error.HTTPError as e:
        if e.code != 400:  # 400 = already exists
            raise
    install_scanner(log)
    work = C.lfg_path("tmp", "sonar-work", rid)
    props = dict(_props(root), **{"sonar.projectKey": key, "sonar.scm.disabled": "true",
                                  "sonar.working.directory": work, "sonar.qualitygate.wait": "false"})
    props.setdefault("sonar.sources", ".")
    props.setdefault("sonar.javascript.node.maxspace", "4096")
    props.setdefault("sonar.exclusions", "**/node_modules/**,**/build/**,**/dist/**,**/.next/**,**/coverage/**")
    snap, copied, skipped = stage(rid, root)
    log("    scanning %d files from %s (git-tracked and new; %d ignored or secret-looking left out); this can take "
        "several minutes on a big repo" % (copied, root, skipped))
    props["sonar.projectBaseDir"] = snap
    argv = [C.which("node") or "node", scanner_js()] + ["-D%s=%s" % kv for kv in sorted(props.items())]
    t0 = time.time()
    try:  # the token goes in the environment, never on argv
        cp = C.run(argv, cwd=snap, timeout=timeout_s, env={
            "SONAR_TOKEN": c["token"], "SONAR_HOST_URL": URL, "SONAR_USER_HOME": C.lfg_path("sonarqube", "home")})
    finally:
        import shutil
        shutil.rmtree(snap, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    out = (cp.stdout or "") + (cp.stderr or "")
    task = re.search(r"api/ce/task\?id=([\w-]+)", out)
    if cp.returncode or not task:
        lines = [ln for ln in out.splitlines() if c["token"] not in ln]
        key_lines = [ln for ln in lines if re.search(r"\bERROR\b|Caused by|EXECUTION FAILURE", ln)]
        tail = "\n".join(key_lines[-8:] or lines[-30:])
        raise Problem("the scanner failed (exit %d):\n%s" % (cp.returncode, tail))
    while True:  # wait for SonarQube to process the report
        t = _api("/api/ce/task?id=%s" % task.group(1), auth=c["token"]).get("task") or {}
        if t.get("status") in ("SUCCESS", "FAILED", "CANCELED"):
            break
        if time.time() - t0 > timeout_s:
            raise Problem("SonarQube is still processing the report; check %s" % URL)
        time.sleep(3)
    if t.get("status") != "SUCCESS":
        raise Problem("SonarQube couldn't process the report: %s" % (t.get("errorMessage") or t.get("status")))
    # reading results needs browse rights the analysis-only token doesn't have: use the local admin login
    return _collect(rid, root, key, base, (c["user"], c["password"]), round(time.time() - t0))


def _collect(rid, root, key, base, token, seconds):
    gate = _api("/api/qualitygates/project_status?projectKey=%s" % key, auth=token).get("projectStatus") or {}
    issues = _paged("/api/issues/search?componentKeys=%s&resolved=false" % key, token, "issues")
    spots = _paged("/api/hotspots/search?project=%s&status=TO_REVIEW" % key, token, "hotspots")
    measures = {m["metric"]: m.get("value") for m in (_api(
        "/api/measures/component?component=%s&metricKeys=bugs,vulnerabilities,code_smells,security_hotspots,"
        "duplicated_lines_density,ncloc" % key, auth=token).get("component") or {}).get("measures") or []}
    mb = _base(root, base)
    changed = _changed_lines(root, mb) if mb else {}
    branch = C.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=30).stdout.strip()
    head = C.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=30).stdout.strip()
    base_name = base or (C.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root,
                               timeout=30).stdout.strip() or "origin/main")

    def where(x):
        comp = x.get("component", "")
        return comp.split(":", 1)[1] if ":" in comp else comp

    rows = []
    for i in issues:
        path, line = where(i), i.get("line")
        rows.append({"key": i.get("key"), "kind": i.get("type"), "severity": i.get("severity"),
                     "impacts": [x.get("severity") for x in i.get("impacts") or []], "rule": i.get("rule"),
                     "message": i.get("message"), "path": path, "line": line, "effort": i.get("effort"),
                     "mine": bool(line and line in changed.get(path, ()))})
    for h in spots:
        path, line = where(h), h.get("line")
        rows.append({"key": h.get("key"), "kind": "SECURITY_HOTSPOT", "severity": h.get("vulnerabilityProbability"),
                     "rule": h.get("ruleKey"), "message": h.get("message"), "path": path, "line": line,
                     "mine": bool(line and line in changed.get(path, ()))})
    order = {"BLOCKER": 0, "CRITICAL": 1, "HIGH": 1, "MAJOR": 2, "MEDIUM": 2, "MINOR": 3, "LOW": 3, "INFO": 4}
    rows.sort(key=lambda r: (not r["mine"], order.get(str(r["severity"]), 5), r["path"] or "", r["line"] or 0))
    res = {"ts": C.now_iso(), "root": root, "base": mb, "project": key, "branch": branch, "head": head,
           "base_name": re.sub(r"^origin/", "", base_name), "url": "%s/dashboard?id=%s" % (URL, key),
           "seconds": seconds, "gate": gate.get("status"),
           "conditions": [{k: x.get(k) for k in ("metricKey", "status", "actualValue", "errorThreshold",
                                                   "comparator")} for x in gate.get("conditions") or []],
           "measures": measures, "issues": rows[:2000], "total": len(rows),
           "mine": sum(1 for r in rows if r["mine"]), "changed_files": len(changed)}
    C.write_json(C.lfg_path("repos", rid, "sonar.json"), res)
    return res


def last(rid):
    return C.read_json(C.lfg_path("repos", rid, "sonar.json"), None)


def cloud(root, ref="HEAD"):
    """SonarCloud's own verdict for a pushed commit, from its GitHub check run (read-only through gh)."""
    sha = C.run(["git", "rev-parse", ref], cwd=root, timeout=30).stdout.strip()
    url = C.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=root, timeout=60)
    if not sha or url.returncode:
        return None
    cp = C.run(["gh", "api", "repos/%s/commits/%s/check-runs" % (url.stdout.strip(), sha)], cwd=root, timeout=60)
    try:
        runs = json.loads(cp.stdout or "{}").get("check_runs") or []
    except ValueError:
        return None
    hit = next((r for r in runs if "sonar" in (r.get("name") or "").lower()), None)
    if not hit:
        return {"found": False, "sha": sha}
    out = hit.get("output") or {}
    return {"found": True, "sha": sha, "name": hit.get("name"), "conclusion": hit.get("conclusion"),
            "status": hit.get("status"), "title": out.get("title"),
            "summary": re.sub(r"<[^>]+>", "", out.get("summary") or "")[:4000], "url": hit.get("details_url")}
