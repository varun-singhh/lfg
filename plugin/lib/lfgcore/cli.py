"""`lfg` command line. See CONTRACT.md for the interface."""
import argparse
import json
import os
import re
import sqlite3
import sys

from . import common as C

TOOLS = [  # (command, needed for, pack): a tool is required only when its pack is on
    ("git", "everything", "core"), ("python3", "lfg CLI", "core"), ("uv", "Python tools", "core"),
    ("code-review-graph", "code graph", "core"), ("graphify", "architecture graph", "core"),
    ("gh", "PR/CI status (read-only)", "core"),
    ("gitleaks", "secret scan", "security"), ("semgrep", "/lfg:secure code scan", "security"),
    ("osv-scanner", "/lfg:secure deps", "security"), ("trivy", "/lfg:secure + ship check scans", "security"),
    ("hadolint", "Dockerfile lint", "security"), ("actionlint", "workflow lint", "security"),
    ("zizmor", "workflow security", "security"), ("picklescan", "model-file scan", "security"),
    ("docker", "ship check, pentest sandbox", "shipcheck"),
    ("ollama", "pentest model", "pentest"), ("strix", "pentest", "pentest"),
    ("omnigraph", "dev-graph/second-brain", "knowledge"), ("node", "dev-graph/second-brain MCP", "knowledge"),
    ("headroom", "token compression", "headroom"),
]


def plugin_dir():
    return C.PLUGIN_DIR


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------- doctor

def doctor(selftest=False):
    from . import claudecfg as CC
    from . import guard, shipcheck
    from . import setup as SU
    rows, bad = [], 0

    def row(name, ok, detail="", required=True):
        nonlocal bad
        bad += (not ok) and required
        rows.append(("ok " if ok else ("ERR" if required else "-- "), name, detail))

    row("lfg", True, "%s, home %s" % (C.VERSION, C.LFG_HOME))
    for cmd, why, pack in TOOLS:
        on = SU.pack_on(pack)
        have = bool(SU.which(cmd))
        row(cmd, have, why if have else "missing (%s) - %s" % (
            why, "run `lfg setup`" if pack == "core" else "`lfg add %s`" % pack), on)
    row("Claude Code", bool(SU.which("claude")), "" if SU.which("claude") else "install Claude Code first")
    row("LFG registered with Claude Code", SU._marketplace_known(), "" if SU._marketplace_known() else
        "run `lfg setup`")
    root = C.repo_root()
    if root:
        on = C.is_enabled(root)
        row("LFG on in this repo", on, C.git_main_root_fast(root) if on else "off here - `lfg enable` to turn it on",
            False)
    st = C.enabled_state()
    row("where LFG is on", True, "every repo" if st["everywhere"] else "%d repo(s)" % len(st["repos"]))
    if SU.pack_on("shipcheck"):
        ok, why = shipcheck.docker_ok()
        row("docker daemon", ok, why)
        if ok:
            left = shipcheck.leftovers()
            row("no orphan ship-check resources", not any(left.values()),
                "" if not any(left.values()) else "run `lfg shipcheck --cleanup`: %s" % left)
    from . import headroom as HR
    if HR.routed() or CC.find(tag=HR.ROUTE_TAG):
        live = HR.live()
        row("headroom proxy", live, "Claude Code -> %s -> %s" % (HR.local_url(), HR.status()["upstream"]) if live
            else "Claude Code is pointed at a proxy that is down: `lfg headroom restart` or `lfg headroom off`")
    if SU.pack_on("knowledge"):
        from . import omnigraph as OG
        for name, gs in OG.status()["graphs"].items():
            row("omnigraph %s" % name, gs["ready"] and gs["launchd"],
                ("not set up - run `lfg add knowledge`" if not gs["created"] else
                 "server down - run `lfg omnigraph restart %s`" % name) if not gs["ready"] else
                gs["url"] if gs["launchd"] else
                "%s, but not kept running by its login agent - run `lfg omnigraph restart %s`" % (gs["url"], name),
                False)
    gh = C.run(["gh", "auth", "status"], timeout=15) if SU.which("gh") else None
    row("gh signed in", bool(gh and gh.returncode == 0), "" if gh and gh.returncode == 0 else
        "run `gh auth login` yourself", False)
    row("plugin hooks", os.path.exists(os.path.join(plugin_dir(), "hooks", "hooks.json")), plugin_dir())
    legacy = SU.legacy_items()
    row("no machine-wide leftovers from older LFG", not legacy,
        "" if not legacy else "%d found - `lfg setup --migrate` would undo: %s" % (
            len(legacy), "; ".join(i["title"] for i in legacy)), False)
    row("change ledger", True, "%d change(s) outside ~/.lfg, all undoable (`lfg changes`)" % len(CC.entries()))
    for line in rows:
        print("%s  %-32s %s" % line)
    if selftest:
        fails = guard.selftest()
        print("\nguard self-test: %d case(s), %d failure(s)" % (len(guard.SELFTEST), len(fails)))
        for f in fails:
            print("  FAIL", f)
        bad += len(fails)
    return 1 if bad else 0


# ---------------------------------------------------------------- setup / enable / packs / changes / uninstall

def _yes(q, default=True):
    if not sys.stdin.isatty():
        return default
    try:
        a = input("%s [%s] " % (q, "Y/n" if default else "y/N")).strip().lower()
    except EOFError:
        return default
    return default if not a else a in ("y", "yes")


def cmd_setup(a):
    from . import setup as SU
    if sys.platform != "darwin":
        C.die("LFG supports macOS only for now.", 2)
    packs = ["core"] + [x for x in (a.packs or "").split(",") if x and x != "core"]
    unknown = [x for x in packs if x not in SU.PACKS]
    if unknown:
        C.die("unknown pack(s): %s (choose from %s)" % (", ".join(unknown), ", ".join(SU.PACKS)), 2)
    here = os.getcwd() if a.here else None
    sc = SU.scan()
    steps = SU.plan(packs, here=here, everywhere=a.everywhere, legacy=a.migrate)
    if a.json and a.dry_run:
        _print({"scan": sc, "plan": steps})
        return 0
    print("LFG %s setup\n" % C.VERSION)
    print("Looked at your machine (read-only):")
    print("  Claude Code     %s" % (sc["claude"]["version"] or "NOT FOUND - install it first"))
    if sc["managed_settings"]:
        print("  managed policy  %s (LFG never changes it)" % sc["managed_settings"])
    if sc["cloud_provider"]:
        print("  API provider    %s (Headroom is not available)" % sc["cloud_provider"])
    if sc["base_url_host"]:
        print("  API endpoint    %s (left as is)" % sc["base_url_host"])
    if sc["user_hooks"]:
        print("  your hooks      %s (left as is)" % ", ".join(sc["user_hooks"]))
    if sc["skill_collisions"]:
        print("  same-name skills %s: yours keep the short name; LFG's are /lfg:<name>"
              % ", ".join("/" + n for n in sc["skill_collisions"]))
    print("  disk free       %s GB" % sc["disk_free_gb"])
    if not steps:
        from . import updates as U
        U.remember_source(C.LFG_ROOT)
        print("\nNothing to do: LFG is installed and up to date. `lfg enable` turns it on in a repo.")
        _print_whats_new(SU)
        return 0
    print("\nPlan (nothing has changed yet):")
    for i, st in enumerate(steps, 1):
        mark = "skip" if st.get("conflict") or st.get("manual") or not st["default"] else "do  "
        print("  %2d. [%s] %s" % (i, mark, st["title"]))
        for ch in st["changes"]:
            print("            - %s" % ch)
        if st.get("conflict"):
            print("            ! %s" % st["conflict"])
    print("\nLFG stays off in your repos until you run `lfg enable` in one (or pass --here). Every change outside"
          "\n%s is recorded; `lfg changes` lists them and `lfg uninstall` undoes them." % C.LFG_HOME)
    if a.dry_run:
        return 0
    if not a.yes and not _yes("\nApply this plan?"):
        print("Nothing changed.")
        return 1
    res = SU.apply(steps, packs=packs, here=here, yes=a.yes)
    print("")
    for r in res["results"]:
        if r["status"] != "done" or r["note"]:
            print("  %-8s %s %s" % (r["status"], r["id"], r["note"]))
    if not res["ok"]:
        print("\nSetup stopped; the changes it made outside %s were undone." % C.LFG_HOME)
        return 1
    from . import updates as U
    U.remember_source(C.LFG_ROOT)
    print("\nDone. Next:\n  cd <your repo> && lfg enable     turn LFG on there\n  lfg ui                         "
          "dashboard (packs, settings, skills)\n  lfg doctor                     check everything")
    _print_whats_new(SU)
    from . import onboard as OB
    if not a.yes and OB.interactive():
        from . import ghstar
        ghstar.ask_once()  # once, only with a yes, only when the GitHub CLI is signed in
    if not OB.is_complete():
        print("\nPick the features you'll use: lfg ui (opens Welcome) or lfg onboard")
        if not a.yes and OB.interactive():
            try:
                go = input("Open the dashboard now? [Y/n] ").strip().lower() in ("", "y", "yes")
            except EOFError:
                go = False
            if go:
                print("Starting the dashboard (Ctrl-C stops it; run `lfg ui` any time).")
                return main(["ui"])
    return 0


def _print_whats_new(SU):
    lines = SU.whats_new()
    if lines:
        print("\nNew in LFG %s:\n%s" % (C.VERSION, "\n".join("  - " + x for x in lines)))


def cmd_enable(a):
    from . import setup as SU
    try:
        if a.everywhere:
            SU.enable_everywhere(True)
            print("LFG is on in every repo. `lfg disable --everywhere` turns that off again.")
            return 0
        res = SU.enable(a.path or os.getcwd(), hardened=True if a.hardened else None)
    except (ValueError, RuntimeError) as e:
        C.die(str(e))
    print("LFG is on in %s:\n  %s\nStart (or restart) Claude Code there; `lfg disable` turns it off and undoes this."
          % (res["repo"], "\n  ".join(res["done"])))
    return 0


def cmd_disable(a):
    from . import setup as SU
    try:
        if a.everywhere:
            SU.enable_everywhere(False)
            print("LFG is no longer on in every repo (repos you enabled one by one stay on).")
            return 0
        res = SU.disable(a.path or os.getcwd())
    except (ValueError, RuntimeError) as e:
        C.die(str(e))
    print("LFG is off in %s (%d change(s) undone; its graphs and runs are kept)." % (res["repo"], len(res["undone"])))
    return 0


def cmd_packs(a):
    from . import setup as SU
    if a.action == "list":
        rows = SU.packs_view()
        if a.json:
            _print(rows)
        else:
            for r in rows:
                print("%-4s %-11s %s%s" % ("on" if r["on"] else "off", r["name"], r["about"],
                                           "  (missing: %s)" % ", ".join(r["missing"]) if r["on"] and r["missing"]
                                           else ""))
        return 0
    try:
        res = SU.add_pack(a.name, yes=a.yes, allow_scripts=not a.no_scripts) if a.action == "add" \
            else SU.remove_pack(a.name)
    except (ValueError, RuntimeError) as e:
        C.die(str(e))
    print(json.dumps(res, indent=2) if a.json else "\n".join(
        ["%s pack: %s" % (a.name, "on" if a.action == "add" else "off")] + ["  " + n for n in res.get("notes", [])]))
    return 0


def cmd_changes(a):
    from . import claudecfg as CC
    if a.action == "undo":
        if not a.id:
            C.die("usage: lfg changes undo <id>", 2)
        try:
            r = CC.undo(int(a.id))
        except ValueError as e:
            C.die(str(e))
        print("#%s %s: %s" % (r["id"], r["status"], r["note"]))
        return 0 if r["status"] != "failed" else 1
    es = CC.entries()
    if a.json:
        _print(es)
        return 0
    if not es:
        print("LFG has changed nothing outside %s." % C.LFG_HOME)
    for e in es:
        print("#%-3d %s  %-9s %s  (%s)" % (e["id"], e["ts"][:16], e.get("group") or "", CC.describe(e),
                                           e.get("why") or ""))
    return 0


def cmd_uninstall(a):
    from . import setup as SU
    if not a.dry_run and not a.yes:
        r = SU.uninstall(dry_run=True, keep_data=a.keep_data)
        _uninstall_report(r, True)
        if not _yes("\nUninstall LFG?", default=False):
            print("Nothing changed.")
            return 1
    r = SU.uninstall(dry_run=a.dry_run, keep_data=a.keep_data)
    _uninstall_report(r, a.dry_run)
    return 0


def _uninstall_report(r, dry):
    print("%s:" % ("Would undo" if dry else "Undone"))
    for x in r["undone"]:
        print("  - %s" % x["note"])
    for t in r["legacy"]:
        print("  - %s" % t)
    for x in r["kept"]:
        print("  kept: %s" % x["note"])
    if r["removed"]:
        print("  - remove %s" % r["removed"])
    if r["graph_dirs_left"]:
        print("Graph folders stay in your repos (git-ignored; delete them if you don't need them):\n  %s"
              % "\n  ".join(r["graph_dirs_left"]))
    if r["tools_left"]:
        print("Tools LFG installed stay (other tools may use them); remove any you don't want: %s"
              % ", ".join(sorted(set(r["tools_left"]))))


# ---------------------------------------------------------------- commands

def cmd_graphs(a):
    from . import graphs as G
    root, rid = C.need_repo()
    if a.action == "status":
        res = G.status(root, rid)
        C.emit(res, a.json, lambda r: print("graphs: %s (in %s: .code-review-graph/, graphify-out/)"
                                            % (r["status"], r["graphs_dir"])))
        return 0 if res["status"] == "fresh" else 1
    if a.action == "docs":
        from . import docs as D
        res = D.generate(root, rid)
        if not a.quiet:
            C.emit(res, a.json, lambda r: print("docs: %s in %ss -> %s%s" % (
                r["status"], r.get("seconds"), D.gdir(rid), "".join("\n  error: " + e for e in r.get("errors") or []))))
        return 0 if res["status"] == "ok" else 1
    if a.background:
        G.spawn_background(root)
        print("graph sync started in the background")
        return 0
    res = G.ensure(root, rid, allow_stale=a.allow_stale, force_full=a.rebuild)
    _docs_after_sync(root, rid, res)
    if not a.quiet:
        def human(r):
            print("graphs: %s%s" % (r["status"], " (%s)" % r.get("mode") if r.get("mode") else ""))
            for e in r.get("errors") or []:
                print("  error:", e)
            if r["status"] not in ("fresh",):
                print("  log: %s" % r.get("log", ""))
                if r["status"] == "error":
                    print("  Stop here: graphs are not fresh. Fix the error, or continue only if the user typed "
                          "--allow-stale.")
        C.emit(res, a.json, human)
    return 0 if res["status"] == "fresh" or (a.allow_stale and res["status"] == "stale") else 1


def _docs_after_sync(root, rid, res):
    """Wikis, call-flow and playbooks follow the graphs: regenerate them in the background when they changed."""
    from . import docs as D
    if res.get("status") == "fresh" and D.due(rid):
        D.spawn_background(root)


def cmd_playbooks(a):
    from . import docs as D
    root, rid = C.need_repo()
    files = D.playbooks(root, rid)
    print("playbooks: %s\n  %s" % (D.playbook_dir(rid), "\n  ".join(files) or "none (build the graphs first)"))
    return 0 if files else 1


def cmd_init(a):
    from . import gate as GT
    from . import graphs as G
    root, rid = C.need_repo()
    docs = C.repo_docs_dir(root)
    cmds, path, _ = GT.commands(root, rid)
    res = G.ensure(root, rid, force_full=a.rebuild)
    _docs_after_sync(root, rid, res)
    print("repo-id:   %s\ngraphs:    %s (%s)\ndocs:      %s\ncommands:  %s %s" % (
        rid, res["status"], res.get("mode", ""), docs, path, json.dumps(cmds)))
    return 0 if res["status"] == "fresh" else 1


def cmd_run(a):
    root, rid = C.need_repo()
    if a.action == "new":
        if not a.arg:
            C.die("usage: lfg run new <slug>", 2)
        had = C.worktree_run(root)
        if had:
            sys.stderr.write("this worktree is already part of run %s; carrying on in it, not starting another\n"
                             % os.path.basename(had))
        print(C.new_run(root, a.arg))
        return 0
    if a.action == "merge":
        return _run_merge(root, rid, a)
    if a.action == "review-stamp":
        try:
            res = C.stamp_review(root)
        except ValueError as e:
            C.die(str(e), 2)
        print("06-review.json: checks %s at commit %s%s" % (res["checks"], res["head"][:12] or "(none)",
                                                         "\n" + res["note"] if res["note"] else ""))
        return 0
    if a.action == "review-status":
        st = C.review_status(root)
        print("review %s%s" % ("stands" if st["stands"] else "needs redoing", ": " + st["why"] if st["why"] else ""))
        return 0 if st["stands"] else 1
    if a.action == "path":
        r = C.current_run(root)
        if not r:
            from . import teamknowledge as K
            old = K.legacy_current(root)
            if old:
                sys.stderr.write("the current run %s is still in ~/.lfg from before runs moved into the repo: run "
                                 "`lfg knowledge migrate` (or --dry-run first), don't start a new one\n" % old)
                return 1
            sys.stderr.write("no current run for %s - start one with `lfg run new <slug>`\n" % rid)
            return 1
        print(os.path.join(r, a.arg) if a.arg else r)
        return 0
    if a.action == "scratch":
        r = C.current_run(root)
        if not r:
            sys.stderr.write("no current run for %s - start one with `lfg run new <slug>`\n" % rid)
            return 1
        print(C.scratch_dir(root, r))
        return 0
    if a.action == "set":
        return _run_set(root, rid, a)
    if a.action in ("skip", "unskip"):
        return _run_skip(root, rid, a)
    if a.action in ("doing", "done"):
        return _run_step(root, rid, a)
    main = C.linked_worktree(root)
    if a.action == "use":
        runs = C.runs_dir(main or root, create=False)
        name = os.path.basename(a.arg or "")
        if not name or not os.path.isfile(os.path.join(runs, name, "run.json")):
            C.die("usage: lfg run use <run-id> (one of `lfg run list`)", 2)
        if main:  # a worktree's run is the one that lists it: move it onto this one
            for d in os.listdir(runs):
                p = os.path.join(runs, d, "run.json")
                meta = C.read_json(p, None) if os.path.isfile(p) else None
                if not isinstance(meta, dict):
                    continue
                wts = [w for w in meta.get("worktrees") or [] if not (isinstance(w, dict) and os.path.realpath(
                    w.get("path") or "") == os.path.realpath(root))]
                if d == name:
                    wts.append({"path": root, "branch": C.git_branch(root), "created": C.now_iso()})
                if wts != (meta.get("worktrees") or []):
                    meta["worktrees"] = wts
                    C.write_json(p, meta)
        else:
            C.write_text(os.path.join(runs, "CURRENT"), name + "\n")
        print("current run: %s" % os.path.join(runs, name))
        return 0
    cur = os.path.basename(C.current_run(root) or "")
    runs = C.runs_dir(main or root, create=False)
    for d in sorted(os.listdir(runs) if os.path.isdir(runs) else [], reverse=True)[:20]:
        if os.path.isdir(os.path.join(runs, d)):
            print(("* " if d == cur else "  ") + d)
    return 0


def _run_merge(root, rid, a):
    """`lfg run merge <from-run> [<into-run>]`: two runs started for one piece of work (e.g. one in a worktree that
    couldn't see the main checkout's). Moves from-run's files into into-run (default: the current run) and removes
    from-run; see common.merge_runs for files both have."""
    from . import dash
    found = dash._run_dirs(rid)
    src = found.get(os.path.basename(a.arg or ""))
    dst = found.get(os.path.basename(a.more[0])) if a.more else C.current_run(root)
    if not src or not dst:
        C.die("usage: lfg run merge <from-run> [<into-run>] (run ids from the dashboard's Runs page or `lfg run "
              "list`; into-run defaults to the current run)", 2)
    try:
        res = C.merge_runs(src, dst)
    except ValueError as e:
        C.die(str(e), 2)
    dash._CACHE.clear()
    print("merged %s into %s: %d file(s) moved, %d already there%s" % (
        os.path.basename(res["from"]), res["into"], len(res["copied"]), len(res["same"]),
        "".join("\n  both had %s: kept this run's, saved the other beside it as .from-%s" % (f, os.path.basename(
            res["from"])) for f in res["kept_both"])))
    return 0


def _run_skip(root, rid, a):
    """`lfg run skip <step> "<reason>"`: a step left out on purpose (e.g. design, when the ticket settled it). The
    dashboard shows it as skipped with the reason, and the next step moves past it. `lfg run unskip <step>` undoes."""
    from . import dash
    r = C.current_run(root)
    if not r:
        C.die("no current run for %s - start one with `lfg run new <slug>`" % rid)
    steps = [k for k, _, _ in dash.STAGES]
    reason = " ".join(a.more or []).strip()
    if a.arg not in steps or (a.action == "skip" and not reason):
        C.die('usage: lfg run %s <%s>%s' % (a.action, "|".join(steps), ' "<why>"' if a.action == "skip" else ""), 2)
    p = os.path.join(r, "run.json")
    meta = C.read_json(p, {}) or {}
    skipped = dict(meta.get("skipped") or {})
    if a.action == "skip":
        skipped[a.arg] = reason[:300]
    else:
        skipped.pop(a.arg, None)
    meta.update(skipped=skipped, updated=C.now_iso())
    C.write_json(p, meta)
    print("run.json: skipped %s" % (", ".join("%s (%s)" % kv for kv in skipped.items()) or "nothing"))
    return 0


def _run_step(root, rid, a):
    """`lfg run doing <step>` / `lfg run done <step>`: a step started, or finished. The run page shows a started one in
    progress (not done) even once its file exists, as a brief grill has drafted but you haven't approved yet."""
    from . import dash
    r = C.current_run(root)
    if not r:
        C.die("no current run for %s - start one with `lfg run new <slug>`" % rid)
    steps = [k for k, _, _ in dash.STAGES]
    if a.arg not in steps:
        C.die("usage: lfg run %s <%s>" % (a.action, "|".join(steps)), 2)
    p = os.path.join(r, "run.json")
    meta = C.read_json(p, {}) or {}
    marks = dict(meta.get("steps") or {}, **{a.arg: a.action})
    meta.update(steps=marks, updated=C.now_iso())
    C.write_json(p, meta)
    print("run.json: %s %s" % (a.arg, "in progress" if a.action == "doing" else "done"))
    return 0


def _run_set(root, rid, a):
    """`lfg run set lane=standard stage=plan issue=ACME-4225`: record them in run.json; a stage moves the linked
    Issue in dev-graph. Lanes only go up unless --force (checkpoint 6: only the user lowers a lane)."""
    from . import tracker as T
    r = C.current_run(root)
    if not r:
        C.die("no current run for %s - start one with `lfg run new <slug>`" % rid)
    pairs = ([a.arg] if a.arg else []) + list(a.more or [])
    kv = dict(x.split("=", 1) for x in pairs if "=" in x)
    if not kv or len(kv) != len(pairs) or set(kv) - {"lane", "stage", "issue"}:
        C.die("usage: lfg run set [lane=<%s>] [stage=<%s>] [issue=<ID or title>]" % (
            "|".join(T.LANES), "|".join(T.STAGES)), 2)
    if "lane" in kv and kv["lane"] not in T.LANES:
        C.die("lane must be one of %s" % ", ".join(T.LANES), 2)
    if "stage" in kv and kv["stage"] not in T.STAGES:
        C.die("stage must be one of %s" % ", ".join(T.STAGES), 2)
    p = os.path.join(r, "run.json")
    meta = C.read_json(p, {}) or {}
    rank = {"express": 0, "standard": 1, "full": 2, "hotfix": 2}
    old, new = meta.get("lane"), kv.get("lane")
    if old and new and rank[new] < rank.get(old, 0) and not a.force:
        C.die("lane %s -> %s would lower it; only the user can (re-run with --force once they said so)" % (old, new))
    meta.update(kv)
    if "issue" in kv:
        meta["issue"] = T.resolve(kv["issue"])
    meta["updated"] = C.now_iso()
    C.write_json(p, meta)
    print("run.json: %s" % ", ".join("%s=%s" % (k, meta[k]) for k in ("lane", "stage", "issue") if meta.get(k)))
    if "stage" in kv and meta.get("issue"):
        try:
            res = T.set_status(meta["issue"], T.STAGES[kv["stage"]])
            print("dev-graph: %s -> %s" % (res["slug"], res["status"]))
        except Exception as e:  # bookkeeping must not stop the pipeline; say so instead
            print("dev-graph: NOT updated (%s)" % (getattr(e, "reason", None) or e))
    return 0


def cmd_knowledge(a):
    """`lfg knowledge sync | status | migrate [--dry-run] [--take-main-nodes]`: see teamknowledge.py.
    `lfg knowledge tag <slug>`: the Knowledge page's repo, feature and topic tags, see knowledge.py."""
    if a.action == "tag":
        from . import knowledge as KN
        if not a.slug:
            C.die("tag needs the item's slug", 2)
        try:
            _print(KN.set_tags(a.slug, repo=a.repo, feature=a.feature, topic=a.topic))
        except ValueError as e:
            C.die(str(e), 2)
        return 0
    from . import teamknowledge as K
    root, rid = C.need_repo()
    if a.action == "status":
        last = K.last_sync(root)
        files, bad = K.read_files(root)
        out = {"folder": C.knowledge_dir(root, create=False), "repo_id": rid, "branch": K.branch_for(root),
               "node_files": len(files), "bad_files": bad, "last_sync": last.get("synced_at"),
               "from_before": {k: {x: len(v) for x, v in w.items()} for k, w in K.legacy(root).items()},
               "hidden_from_git": K.hidden_by_exclude(root)}
        C.emit(out, a.json, lambda o: print("\n".join("%s: %s" % kv for kv in o.items())))
        return 0
    if a.action == "migrate":
        res = K.migrate(root, dry_run=a.dry_run)
        if a.take_main_nodes and not a.dry_run:
            res["took_from_main"] = K.take_main_nodes(root)

        def human(r):
            if not r["from"]:
                print("nothing in ~/.lfg to move for this repo")
                return
            print("%s %d run(s) from %s into %s" % ("would move" if r["dry_run"] else "moved", len(r["runs"]),
                                                   ", ".join(r["from"]), r["to"]))
            for p in r["kept_both"]:
                print("  kept both, merge by hand: %s" % p)
            for p in r["left"]:
                print("  left in place (live /build worktrees): %s" % p)
            if r.get("backup"):
                print("originals: %s" % r["backup"])
            if r.get("unhidden"):
                print(".lfg/ is visible to git again (took back the line an older `lfg enable` put in "
                      ".git/info/exclude)")
            if r.get("took_from_main") is not None:
                print("copied %d node(s) from dev-graph main" % len(r["took_from_main"]))
            if not r["dry_run"]:
                print("The files are unstaged in .lfg/: review and commit them with your work.")
        C.emit(res, a.json, human)
        return 0
    try:
        res = K.sync_locked(root)
    except RuntimeError as e:
        if a.quiet:
            return 1
        C.die("dev-graph: %s" % e)
    if not a.quiet:
        C.emit(res, a.json, lambda r: print(
            "knowledge: %s" % r["skipped"] if r.get("skipped") else
            "knowledge: %d node file(s) on %s%s%s%s" % (
                r["files"], r["branch"], ", rebuilt" if r["rebuilt"] else "",
                "".join("\n  from the graph: %s" % k for k in r["written"]),
                "".join("\n  changed on both sides, kept the file: %s" % k for k in r["conflicts"]) +
                "".join("\n  unreadable: %s" % b for b in r["bad"]))))
    return 0


def cmd_worktree(a):
    """`lfg worktree new <branch> [--from <ref>] | list | remove <name> | merge <name>|--all --into <base> [--remove]
    [--merge-commit]`: see worktree.py."""
    from . import worktree as W
    root, rid = C.need_repo()
    if a.action == "list":
        for w in W.status(root):
            line = "%s %-30s %-10s %s" % ("*" if w["lfg"] else " ", w["branch"] or "(detached)", w["head"], w["path"])
            if w["base"]:
                line += "  -> %s (%d ahead, %d behind%s)" % (w["base"], w["ahead"], w["behind"],
                                                           ", %d uncommitted" % w["dirty"] if w["dirty"] else "")
            print(line)
        print("(* = made by lfg worktree, in %s)" % W.base_dir(root))
        return 0
    if a.action == "merge":
        try:
            if a.all:
                if not a.into:
                    C.die("usage: lfg worktree merge --all --into <branch> [--remove]", 2)
                done = W.merge_all(root, a.into, a.remove, a.merge_commit)
            elif a.name:
                done = [W.merge(root, a.name, a.into, a.remove, a.merge_commit)]
            else:
                C.die("usage: lfg worktree merge <name> [--into <branch>] [--remove] | --all --into <branch>", 2)
        except W.NeedsMergeCommit as e:
            C.die("%s Run again with --merge-commit." % e)
        except (ValueError, RuntimeError) as e:
            C.die(str(e))
        for r in done:
            print("%s: %s into %s (%s, %d commit%s)%s" % (r["name"], r["branch"], r["into"], r["how"], r["commits"],
                                                         "" if r["commits"] == 1 else "s",
                                                         ", worktree removed" if r["removed"] else ""))
        if not done:
            print("no LFG worktree forked from %s" % a.into)
        return 0
    if not a.name:
        C.die("usage: lfg worktree %s <%s>" % (a.action, "branch" if a.action == "new" else "name|branch"), 2)
    try:
        if a.action == "new":
            res = W.new(root, a.name, a.base)
        else:
            res = W.remove(root, a.name)
    except (ValueError, RuntimeError) as e:
        C.die(str(e))
    r = C.current_run(root)
    if r:
        p = os.path.join(r, "run.json")
        meta = C.read_json(p, {}) or {}
        wts = [w for w in meta.get("worktrees", []) if w.get("path") != res["path"]]
        if a.action == "new":
            wts.append({"path": res["path"], "branch": res["branch"], "created": C.now_iso()})
        meta["worktrees"] = wts
        C.write_json(p, meta)
    if a.action == "new":
        print("worktree: %s (branch %s%s)\ngraphs:   shared with %s (code-review-graph tools: repo_root=%s)" % (
            res["path"], res["branch"], ", new" if res["created_branch"] else "", C.main_root(root),
            C.main_root(root)))
    else:
        print("removed: %s (branch %s kept)" % (res["path"], res["branch"]))
    return 0


def cmd_issue(a):
    """`lfg issue sync <ID|title> [--title ..] [--type ..] [--status ..] [--priority N] [--description ..]
    [--criteria ..]`, `lfg issue sync-tasks` (the current run's tasks.json) or `lfg issue sync-brief` (its brief):
    mirror into dev-graph."""
    from . import tracker as T
    if a.action in ("sync", "show") and not a.key:
        C.die("usage: lfg issue %s <ID|title>" % a.action, 2)
    try:
        if a.action == "show":
            slug = T.resolve(a.key, new=False)  # never make up a key just to say it isn't there
            out = (T.lookup(slug) if slug else None) or {"slug": slug or T.slug_for(a.key), "found": False}
        elif a.action in ("sync-tasks", "sync-brief"):
            root, _ = C.need_repo()
            run = C.current_run(root)
            if not run:
                C.die("no current run - start one with `lfg run new <slug>`", 1)
            if a.action == "sync-brief":
                out = T.sync_brief(run)
            else:
                rows = T.sync_tasks(run)
                out = {"tasks": len(rows), "created": sum(r["action"] == "created" for r in rows),
                       "done": sum(r.get("status") == "done" for r in rows)}
        else:
            out = T.sync(a.key, title=a.title, issue_type=a.type, status=a.status, priority=a.priority,
                         description=a.description, criteria=a.criteria)
    except Exception as e:
        C.die("dev-graph: %s" % (getattr(e, "reason", None) or e))
    if a.json:
        _print(out)
    else:
        print(" ".join("%s=%s" % kv for kv in out.items()))
    return 0


def cmd_rule(a):
    from . import settings as S
    name = os.path.basename(a.name)
    text = S.rule_text(name)
    if text is None:
        C.die("unknown rule %r. Available: %s" % (name, ", ".join(S.rule_names())), 2)
    sys.stdout.write(text)
    return 0


def cmd_repo(a):
    root, rid = C.need_repo()
    if a.action == "root":
        print(C.main_root(root))
    elif a.action == "graph":
        print(os.path.join(C.main_root(root), "graphify-out", "graph.json"))
    elif a.action == "knowledge":
        print(C.ensure_dir(C.lfg_path("repos", rid, "knowledge")))
    elif a.action == "docs" and a.branch is not None:
        branch = a.branch or C.git_branch(root)
        if not branch or branch.startswith("detached@"):
            C.die("not on a branch: write it to the project docs (`lfg repo docs`) or pass --branch <name>", 2)
        print(C.branch_docs_dir(root, branch))
    else:
        print(C.repo_docs_dir(root) if a.action == "docs" else rid)
    return 0


def cmd_lane(a):
    from . import gate as GT
    root, rid = C.need_repo()
    res = GT.lane(root, rid)
    C.emit(res, a.json, lambda r: print("lane: %s\n  %s" % (r["lane"], "\n  ".join(r["reasons"]))))
    return 0


def _lean(items, ok, keys=("tail", "detail")):
    """Copies of check dicts without output for the ones that passed: stdout goes into an agent's context, and the
    full output is in the run's log files."""
    return [{k: v for k, v in i.items() if not (ok(i) and k in keys)} for i in items]


def _checks_human(r):
    for c in r["checks"]:
        mark = "skip" if c["exit"] is None else "PASS" if c["exit"] == 0 else "N/A" if c.get("cant_run") else "FAIL"
        print("%-5s %-13s %s" % (mark, c["name"], c.get("cmd") or ""))
        if c.get("cant_run"):
            print("      can't run here: " + c["hint"])
        elif c["exit"] not in (0, None) and c.get("tail"):
            print("      " + c["tail"].replace("\n", "\n      "))
        elif c["exit"] is None:
            print("      " + c.get("tail", ""))
    print("\ngate: %s" % ("GREEN" if r["green"] else "NOT PROVEN HERE (a tool is missing; nothing failed)"
                         if r.get("state") == "cant_run" else "RED"))
    if r.get("logs"):
        print("full logs: %s" % r["logs"])


def cmd_gate(a):
    from . import gate as GT
    root, rid = C.need_repo()
    res = GT.gate(root, rid, fix=a.fix, affected=a.affected, only=a.only.split(",") if a.only else None)
    C.emit(dict(res, checks=_lean(res["checks"], lambda c: c["exit"] == 0)) if a.json else res, a.json,
           _checks_human)
    return 0 if res["green"] else 1


def cmd_ci_local(a):
    from . import gate as GT
    root, _rid = C.need_repo()

    def progress(ev, n, total, st, extra=None):  # stderr, so --json output stays one object
        what = "[%d/%d] %s: %s" % (n, total, st["workflow"], (st["name"] or "")[:60])
        if ev == "start":
            line = "%s ..." % what
        elif ev == "tick":
            line = "%s still running (%dm%02ds)" % (what, extra // 60, extra % 60)
        else:
            line = "%s %s in %ss" % (what, "PASS" if extra["exit"] == 0 else "FAIL", extra["seconds"])
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    if not a.list and not a.affected:
        sys.stderr.write("ci-local: running every workflow's steps; `lfg ci-local --affected` runs only the "
                         "workflows this branch's changes would start\n")
    res = GT.ci_local(root, list_only=a.list, affected=a.affected, progress=None if a.list else progress)

    def human(r):
        for w in r["workflows_lint"]:
            print("%-5s %s %s" % ("skip" if w["exit"] is None else ("PASS" if w["exit"] == 0 else "FAIL"),
                                  w["tool"], w["tail"] if w["exit"] else ""))
        for s in r["steps"]:
            st = "skip" if s["skipped"] else ("list" if "exit" not in s else ("PASS" if s["exit"] == 0 else "FAIL"))
            print("%-5s %s: %s%s" % (st, s["workflow"], (s["name"] or "")[:60],
                                     " (%s)" % s["skipped"] if s["skipped"] else ""))
            if s.get("exit"):
                print("      " + s["tail"].replace("\n", "\n      "))
        print("\nci-local: %s" % ("GREEN" if r["green"] else "RED"))
    if a.json:
        res = dict(res, workflows_lint=_lean(res["workflows_lint"], lambda w: w["exit"] == 0),
                   steps=_lean(res["steps"], lambda st: st.get("exit") == 0))
    C.emit(res, a.json, human)
    return 0 if res["green"] else 1


def cmd_secure(a):
    from . import secure as S
    root, rid = C.need_repo()
    res = S.secure(root, rid, a.target or "diff", offline=a.offline)

    def human(r):
        print("secure %s: verdict %s (%d blocking)%s" % (
            r["target"], r["verdict"].upper(), r["blocking"],
            "; %d more already on main, in files this branch doesn't touch (not counted)" % r["on_main"]
            if r.get("on_main") else ""))
        for k, v in r["inventory"].items():
            if v:
                print("  new %s: %s" % (k, ", ".join(v[:10])))
        for s in r["scanners"]:
            print("  scanner %-22s %s" % (s["tool"], "not run: " + s.get("note", "") if s["exit"] is None
                                          else "exit %s" % s["exit"]))
        for f in sorted(r["findings"], key=lambda f: bool(f.get("on_main"))):  # the branch's own first
            print("  [%s%s] %s %s @ %s -> %s" % (
                f["severity"], ", already on main" if f.get("on_main") else ", BLOCKING" if f.get("blocking") else "",
                f["id"], f["item"], f["where"], f["fix"]))
    C.emit(res, a.json, human)
    return 1 if res["blocking"] else 0


def cmd_pentest(a):
    from . import pentest as P
    root, rid = C.need_repo()
    res = P.pentest(root, rid, mode=a.mode, target=a.target, model=a.model, dry_run=a.preflight)

    def human(r):
        for c in r["preflight"]:
            print("%-4s %s %s" % ("ok" if c["ok"] else "FAIL", c["check"], "" if c["ok"] else "- " + c["detail"]))
        print("pentest: %s" % r.get("status"))
        if r.get("summary"):
            print("  model %s · %s · gate 4 %s · report %s"
                  % (r["model"], r["summary"], r["gate4"], r["report_dir"]))
    C.emit(res, a.json, human)
    if res["status"] == "refused":
        return 2
    return 1 if res.get("gate4") == "fail" or str(res.get("status", "")).startswith("strix-exit") else 0


def cmd_shipcheck(a):
    from . import shipcheck as S
    if a.cleanup:
        ok, why = S.docker_ok()
        if not ok:
            C.die(why, 2)
        res = S.cleanup(None)
        C.emit(res, a.json, lambda r: print("cleanup: %s %s" % ("clean" if r["clean"] else "LEFTOVERS",
                                                                  r["log"] or "(nothing to remove)")))
        return 0 if res["clean"] else 1
    root, rid = C.need_repo()
    res = S.shipcheck(root, rid)

    def human(r):
        pa = r["part_a"]
        print("Part A (Docker): %s" % ("n/a - " + pa.get("note", "") if not pa["applicable"] else
                                       pa.get("error") or ("PASS" if pa.get("pass") else "FAIL")))
        for c in pa.get("checks", []):
            bad = "warn" if c.get("severity") == "warn" else "FAIL"
            mark = "skip" if c["ok"] is None else ("ok" if c["ok"] else bad)
            print("  %-5s %s %s" % (mark, c["check"], ("- " + c["detail"].splitlines()[0][:150]) if c.get("detail")
                                    and c["ok"] is not True else ""))
        print("Part B (checklist):")
        for i in r.get("checklist", []):
            print("  %2d %-7s %s %s" % (i["n"], i["status"], i["requirement"],
                                        ("- " + i["detail"].splitlines()[0][:150]) if i["detail"] else ""))
        print("\nship check: %s" % ("PASS" if r["pass"] else "FAIL"))
    if a.json and res["part_a"].get("checks"):
        res = dict(res, part_a=dict(res["part_a"], checks=_lean(res["part_a"]["checks"], lambda c: c["ok"] is True)))
    C.emit(res, a.json, human)
    return 0 if res["pass"] else 1


def cmd_watch(a):
    root, _rid = C.need_repo()
    branch = C.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root).stdout.strip()
    cp = C.run(["gh", "run", "list", "--branch", branch, "--limit", "1", "--json", "databaseId,status,conclusion,name"],
               cwd=root, timeout=30)
    runs = json.loads(cp.stdout or "[]") if cp.returncode == 0 else []
    if not runs:
        print("no CI runs for branch %s (or gh not signed in)" % branch)
        return 1
    r = runs[0]
    print("CI: %s · %s · %s" % (r["name"], r["status"], r.get("conclusion") or "running"))
    if r["status"] != "completed":
        return C.run(["gh", "run", "watch", str(r["databaseId"]), "--exit-status"], cwd=root, capture=False).returncode
    return 0 if r.get("conclusion") == "success" else 1


def cmd_feedback(a):
    root, rid = C.need_repo()
    p = C.lfg_path("feedback", rid + ".json")
    fb = C.read_json(p, {}) or {}
    fb[a.finding] = {"verdict": a.verdict, "note": a.note or "", "ts": C.now_iso(),
                     "run": os.path.basename(C.current_run(root) or "")}
    C.write_json(p, fb)
    print("recorded %s: %s" % (a.finding, a.verdict))
    return 0


def cmd_review(a):
    from . import review as R
    try:
        return _review(R, a)
    except R.ReviewError as e:
        C.die(str(e), 1)


def _review(R, a):
    if a.action == "list":
        recs = [r for r in R.all_records() if not a.ticket or r.get("ticket") == a.ticket]
        rows = [{"pr": "%s#%d" % (r["repo"], r["number"]), "title": r.get("title"), "author": r.get("author"),
                 "ticket": r.get("ticket"), "passes": len(r["passes"]), "score": r["passes"][-1].get("score"),
                 "posted": bool(r["passes"][-1].get("posted")), "updated": r.get("updated")} for r in recs]
        C.emit(rows, a.json, lambda rs: [print("%-40s pass %d  %-8s %s" % (x["pr"], x["passes"], "posted" if
                                                x["posted"] else "draft", x["title"] or "")) for x in rs]
               or (None if rs else print("no reviews saved")))
        return 0
    if a.action == "passes":
        if a.remove:
            C.emit(R.pass_remove(a.remove), a.json, lambda o: print("removed %s" % o["removed"]))
            return 0
        rows = R.passes_list(R.parse_pr(a.pr)[0] if a.pr else None)
        C.emit(rows, a.json, lambda rs: [print("%-10s %-5s %-30s %s" % (x["id"], x["scope"], x["repo"] if x["scope"] ==
                                                "repo" else "every repo", x["title"])) for x in rs]
               or (None if rs else print("nothing is passed on for good")))
        return 0
    if not a.pr:
        C.die("usage: lfg review %s <pr>" % a.action, 2)
    repo, number = R.parse_pr(a.pr)
    if a.action == "remember":
        if len(a.ids) != 1 or not a.to:
            C.die("usage: lfg review remember <pr> <id> --to dev-graph|second-brain [--note TEXT]", 2)
        o = R.remember_finding(repo, number, a.ids[0], a.to, note=a.note)
        C.emit(o, a.json, lambda x: print("saved %s to %s as %s" % (x["finding"], x["to"], x["slug"])))
    elif a.action == "pass":
        if len(a.ids) != 1 or not a.scope:
            C.die("usage: lfg review pass <pr> <id> --scope pr|repo|all [--note TEXT]", 2)
        o = R.pass_on(repo, number, a.ids[0], a.scope, note=a.note)
        C.emit(o, a.json, lambda x: print("%s dropped%s" % (x["finding"], "" if x["scope"] == "pr" else
                                                            ", and not flagged again in %s (%s)" % (
                                                                "this repo" if x["scope"] == "repo" else "any repo",
                                                                x["id"]))))
    elif a.action == "context":
        _print(R.context(repo, number))
    elif a.action == "save":
        raw = C.read_text(a.file) if a.file else sys.stdin.read()
        try:
            data = json.loads(raw)
        except ValueError as e:
            C.die("findings are not valid JSON: %s" % e, 2)
        if isinstance(data, dict) and not data.get("reviewer"):
            data["reviewer"] = R.me()
        rec = R.save(repo, number, data, ticket=a.ticket)
        p = rec["passes"][-1]
        print("saved pass %d of %s#%d: %d findings (%s) -> %s" % (
            p["n"], repo, number, len(p["findings"]), ", ".join(f["id"] for f in p["findings"]) or "none",
            R.record_path(repo, number)))
    elif a.action == "show":
        rec = R.need(repo, number)
        C.emit(rec, a.json, _review_human)
    elif a.action == "mark":
        if not a.ids or (a.status is None and a.body is None and a.body_file is None):
            C.die("usage: lfg review mark <pr> <id>... [--keep|--drop|--pending] [--body TEXT|--body-file F]", 2)
        body = C.read_text(a.body_file) if a.body_file else a.body
        R.mark(repo, number, a.ids, status=a.status, body=body)
        print("%s: %s" % (", ".join(a.ids), a.status or "comment updated"))
    elif a.action == "post":
        if not a.event:
            C.die("usage: lfg review post <pr> --event approve|request-changes|comment [--body TEXT] [--dry-run]", 2)
        out = R.post(repo, number, a.event, body=a.body or "", dry_run=a.dry_run)
        if a.json or a.dry_run:
            _print(out)
        else:
            print("posted %s with %d inline comments: %s" % (out["event"], len(out["comments"]), out["posted"]["url"]))
    elif a.action == "threads":
        _print(R.threads(repo, number))
    elif a.action == "others":
        _print(R.others(repo, number))
    elif a.action == "run":
        j = R.run(repo, number, ticket=a.ticket, fresh=a.fresh, together=[R.parse_pr(x) for x in a.with_ or []],
                  model=a.model, method=a.method, fresh_eyes=a.fresh_eyes, notes=a.notes)
        print("review of %s#%d: %s%s (log %s)" % (repo, number, j["status"], " - " + j["why"] if j["why"] else "",
                                                  j["log"]))
        return 0 if j["status"] == "done" else 1
    elif a.action == "fix":
        j = R.fix_run(repo, number)
        print("fix of %s#%d: %s%s (log %s)" % (repo, number, j["status"], " - " + j["why"] if j.get("why") else "",
                                               j["log"]))
        return 0 if j["status"] == "done" else 1
    elif a.action == "sessions":
        rows = R.sessions_for(repo, number)
        C.emit(rows, a.json, lambda rs: [print("%s  %s  %-50s %s" % (x["modified"][:16], "json" if x["has_json"]
                                                else "    ", x["title"][:50], x["path"])) for x in rs]
               or (None if rs else print("no sessions in the last 30 days mention %s#%d" % (repo, number))))
    elif a.action == "import":
        if not a.file:
            C.die("usage: lfg review import <pr> --file <session .jsonl or review .log>  (`lfg review sessions <pr>` "
                  "lists them)", 2)
        rec = R.import_session(repo, number, os.path.expanduser(a.file), ticket=a.ticket)
        p = rec["passes"][-1]
        print("imported pass %d of %s#%d: %d findings" % (p["n"], repo, number, len(p["findings"])))
    return 0


def _review_human(rec):
    print("%s#%d  %s  (by %s)%s" % (rec["repo"], rec["number"], rec.get("title", ""), rec.get("author", ""),
                                    "  ticket " + rec["ticket"] if rec.get("ticket") else ""))
    for p in rec["passes"]:
        print("\npass %d (%s) at %s, %s%s" % (p["n"], p["kind"], p["head_sha"][:8],
                                            "score %s" % p["score"] if p.get("score") is not None else "no score",
                                            ", posted " + p["posted"]["event"] if p.get("posted") else ""))
        if p.get("summary"):
            print("  " + p["summary"].replace("\n", "\n  "))
        for x in p.get("prior") or []:
            print("  earlier %-5s %-18s %s" % (x["id"], x["state"], x["note"]))
        for f in p["findings"]:
            where = "%s:%s" % (f["file"], f["line"] or "") if f["file"] else "(general)"
            print("  %-5s %-7s %-8s %s  %s" % (f["id"], f["status"], f["severity"], f["title"], where))


def cmd_prefs(a):
    from . import prefs as P
    if a.action == "hook":
        return P.hook(a.id or "")
    try:
        if a.action == "set":
            if not a.id or a.value is None:
                C.die("usage: lfg prefs set <id> <value> [--session ID]", 2)
            _print(P.set_pref(a.id, a.value, session=a.session, by_agent=not a.by_user))
        elif a.action == "clear":
            _print(P.clear_session(a.session or a.id))
        elif a.action == "remind":
            _print(P.remind(a.session or a.id))
        elif a.action == "install":
            _print(P.install())
        elif a.action == "status":
            _print(P.installed())
        else:
            d = P.load()
            vals = P.effective(a.session, d)
            for p in P.catalog(d):
                v = vals[p["id"]]
                shown = ("on" if v else "off") if p["kind"] == "switch" else v
                print("%-12s %-22s %-8s %s" % (p["group"], p["id"], shown, p["title"]))
    except PermissionError as e:
        C.die(str(e), 1)
    except ValueError as e:
        C.die(str(e), 2)
    return 0


def cmd_corrections(a):
    from . import corrections as CR
    act, args = a.action, list(a.args or [])
    try:
        if act in ("on", "off"):
            _print(CR.set_enabled(act == "on"))
        elif act == "status":
            _print(CR.summary())
        elif act == "add":
            if not args:
                C.die('usage: lfg corrections add "<what the user said>" [--did ...] [--note ...]', 2)
            _print(CR.add(" ".join(args), did=a.did or "", note=a.note or ""))
        elif act == "show":
            if not args:
                C.die("usage: lfg corrections show <id>", 2)
            x = CR.get(args[0])
            _print(dict(x, similar=CR.similar(x["said"] + " " + x.get("note", ""))))
        elif act == "approve":
            if not args or not a.text:
                C.die('usage: lfg corrections approve <id> --text "<the rule>" [--title] [--why] [--example] '
                      '[--scope global|project]', 2)
            _print(CR.approve(args[0], a.text, title=a.title or "", why=a.why or "", example=a.example or "",
                              scope=a.scope))
        elif act == "merge":
            if len(args) < 2:
                C.die("usage: lfg corrections merge <id> <rule-id> [--text] [--why] [--example]", 2)
            _print(CR.merge(args[0], args[1], text=a.text or "", why=a.why or "", example=a.example or ""))
        elif act == "brain":
            if not args:
                C.die('usage: lfg corrections brain <id> [--title] [--text]', 2)
            _print(CR.to_brain(args[0], a.title or "", a.text or ""))
        elif act == "discard":
            if not args:
                C.die("usage: lfg corrections discard <id> [<id>…]", 2)
            _print(CR.discard(args))
        elif act == "rules":
            for p in CR.rules():
                print("%-3s %-40s %s%s" % ("on" if p["on"] else "off", p["id"], p["title"],
                                          " (only %s)" % os.path.basename(p["repo"]) if p.get("repo") else ""))
        else:
            xs = CR.items("all" if a.all else "pending")
            if a.json:
                _print({"enabled": CR.enabled(), "items": xs})
                return 0
            print("Corrections are %s. %d to review." % ("on" if CR.enabled() else "off",
                                                        len(CR.items("pending"))))
            for x in xs:
                print("%-11s %-10s %-11s %s" % (x["id"], x["status"], x["kind"], x["said"][:90]))
    except ValueError as e:
        C.die(str(e), 2)
    return 0


def cmd_plugins(a):
    from . import plugins as PL
    words = list(a.id or [])
    if a.action != "list" and len(words) != 1:
        C.die("usage: lfg plugins %s <name@marketplace>" % a.action, 2)
    a.id = " ".join(words)
    try:
        if a.action == "install":
            _print(PL.install(a.id))
        elif a.action in ("enable", "disable"):
            _print(PL.set_enabled(a.id, a.action == "enable"))
        elif a.action == "uninstall":
            _print(PL.uninstall(a.id))
        else:
            d = PL.view(a.id or "", fresh=True)
            if a.json:
                _print(d)
                return 0
            for x in d["installed"]:
                print("%-4s %-50s %s" % ("on" if x["enabled"] else "off", x["id"],
                                         "" if x["yours"] else "(one repo only)"))
            for x in d["found"]:
                print("     %-50s %s" % (x["id"], x["about"][:70]))
    except ValueError as e:
        C.die(str(e), 2)
    return 0


def cmd_update(a):
    from . import updates as U
    if a.action in ("apply", "fix"):
        return 0 if (U.apply if a.action == "apply" else U.fix)()["status"] == "done" else 1
    d = U.check(max_age=0)
    if a.json:
        print(U.as_json(d))
    else:
        U.human(d)
    return 0


def cmd_sessions(a):
    from . import sessions as SS
    try:
        if a.action == "name":
            _print(SS.rename(a.id, " ".join(a.value)))
            return 0
        if a.action == "folder":
            _print(SS.file_into(a.id, " ".join(a.value)))
            return 0
        if a.action in ("skill", "run"):
            from . import skillrun as SR
            try:
                if a.action == "run":  # the dashboard's detached worker
                    j = SR.run(a.id)
                    return 0 if j["status"] == "done" else 1
                vals = a.value or []
                skill = vals[0] if vals and vals[0].startswith("/") else ""
                _print(SR.start(a.id, skill=skill, say=" ".join(vals[1:] if skill else vals), times=a.times,
                                until_clean=a.until_clean, mode=a.mode, model=a.model or "", fork=not a.in_place))
                return 0
            except SR.RunError as e:
                C.die(str(e), 2)
    except ValueError as e:
        C.die(str(e), 2)
    d = SS.listing(days=a.days)
    rows = [r for r in d["sessions"] if not a.find or a.find.lower() in " ".join(
        str(r.get(k) or "") for k in ("name", "repo", "branch", "ticket", "folder", "first", "cwd")).lower()]

    def human(rs):
        if not rs:
            print("no sessions match")
        for r in rs[:a.limit]:
            print("%s  %-22s %-12s %s\n    %s" % (r["modified"][:16].replace("T", " "), (r["repo"] + (
                "/" + r["worktree"] if r["worktree"] else ""))[:22], r["group"][:12], r["name"][:70], r["resume"]))
    C.emit(rows[:a.limit], a.json, human)
    return 0


def cmd_usage(a):
    p = C.lfg_path("usage.db")
    rows = []
    if os.path.exists(p):
        db = sqlite3.connect(p)
        rows = db.execute("SELECT repo, model, count(*), sum(input), sum(output), sum(cache_read), sum(cache_write) "
                          "FROM usage GROUP BY repo, model ORDER BY 4 DESC").fetchall()
        db.close()
    res = [dict(zip(["repo", "model", "sessions", "input", "output", "cache_read", "cache_write"], r)) for r in rows]

    def human(rs):
        print("%-30s %-28s %8s %12s %10s %12s" % ("repo", "model", "sessions", "input", "output", "cache_read"))
        for r in rs:
            print("%-30s %-28s %8d %12d %10d %12d" % (r["repo"][:30], r["model"][:28], r["sessions"], r["input"],
                                                      r["output"], r["cache_read"]))
    C.emit(res, a.json, human)
    return 0


VENDOR_REPO = "https://github.com/mattpocock/skills.git"


def cmd_headroom(a):
    from . import headroom as HR
    if a.action == "serve":
        return HR.serve()
    if a.action == "restart":
        return 0 if HR.revive(timeout=60) else 1
    try:
        out = {"setup": lambda: HR.setup(a.upstream, a.scope), "off": HR.off, "status": HR.status}[a.action]()
    except ValueError as e:  # a settings file that isn't valid JSON is left alone
        C.die(str(e))
    if a.json:
        _print(out)
    else:
        for k, v in out.items():
            print("%-9s %s" % (k, v))
    if a.action == "off":
        return 0 if not out["routed"] else 1
    if a.action == "setup":
        return 0 if out["live"] else 1
    return 0 if out["live"] or out["scope"] == "off" else 1


def cmd_onboard(a):
    """Pick the features you use (the dashboard shows only their pages)."""
    from . import onboard as OB
    from . import settings as ST
    try:
        if a.all or a.features is not None:
            v = OB.choose([f.strip() for f in (a.features or "").split(",") if f.strip()], everything=a.all)
        elif OB.interactive() and not a.json:
            v = OB.wizard()
        else:
            v = OB.view()
    except ST.Invalid as e:
        C.die(str(e), 2)
    if a.json:
        _print(v)
        return 0
    on = [f["name"] for f in v["features"] if f["enabled"]]
    print("Features: %s" % (", ".join(on) if v["complete"] else "not chosen yet (every page shows)"))
    print("Dashboard pages: %s" % ", ".join(v["pages"]))
    print("Change: lfg onboard --features %s   (or --all; or Settings > General in lfg ui)" % ",".join(OB.FEATURES))
    return 0


def cmd_hotspots(a):
    """Files that keep needing fixes, with the evidence."""
    root, _ = C.need_repo()
    from . import hotspots_engine as HE
    r = HE.hotspots(root, days=a.days)
    if a.json:
        _print(r)
        return 0
    if not r["files"]:
        print("No hotspots: nothing changed often enough in the last %d days." % r["days"])
        return 0
    print("Hotspots, from %d commits in the last %d days (fixes count most):\n" % (r["commits"], r["days"]))
    for f in r["files"][:a.limit]:
        print("  %s %s\n      %s" % ("!" if f["level"] == "high" else "·", f["path"], "; ".join(f["reasons"])))
    return 0


def cmd_why(a):
    """Why is this code like this? The commits (and issues/PRs) that shaped a file or some lines of it."""
    root, _ = C.need_repo()
    from . import history_engine as HI
    m = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?)?$", a.target)
    path, start, end = m.group(1), m.group(2), m.group(3)
    if not os.path.isfile(os.path.join(root, path)):
        C.die("no such file in this repo: %s" % path, 2)
    r = HI.why(root, path, int(start) if start else None, int(end) if end else None, limit=a.limit)
    if a.json:
        _print(r)
        return 0
    where = path + (":%s-%s" % (r["start"], r["end"]) if r["start"] else "")
    if not r["commits"]:
        print("%s has no history yet (not committed)." % where)
        return 0
    print("%s: %d commit%s by %d %s\n" % (where, len(r["commits"]), "" if len(r["commits"]) == 1 else "s", r["authors"],
                                          "person" if r["authors"] == 1 else "people"))
    for c in r["commits"]:
        print("  %s %s %s%s\n      %s" % (c["sha"][:7], c["date"], c["author"], "  [fix]" if c["fix"] else "",
                                          c["subject"]))
        for ref in c["refs"]:
            print("      -> %s %s" % (ref["label"], ref["url"]))
    return 0


def cmd_explain5(a):
    """Explain a file in plain English."""
    root, _ = C.need_repo()
    from . import explain5_engine as EE

    result = EE.explain_file(a.file, root)

    if a.json:
        _print(result)
        return 0

    if result.get("error"):
        print("Error: %s" % result["error"])
        return 1

    print("File: %s" % result["file"])
    print("\nWhat it does: %s" % result.get("summary", "No summary"))
    print("\nHow it works:")
    for item in result.get("how_it_works", [])[:10]:
        print("  Line %d: %s %s" % (item["line"], item["type"], item["name"]))

    blame = result.get("why_its_here", {})
    if blame:
        print("\nCreated by: %s on %s" % (blame.get("created_by", "?"), blame.get("created_date", "?")))
        print("Last modified: %s on %s" % (blame.get("last_modified_by", "?"), blame.get("last_modified_date", "?")))
        print("Total commits: %s" % blame.get("total_commits", "?"))
        for f in blame.get("recent_fixes") or []:
            print("  fix %s %s: %s" % (f["sha"][:7], f["date"], f["message"]))

    tests = result.get("related_tests", [])
    if tests:
        print("\nRelated tests: %s" % ", ".join(tests[:5]))
    else:
        print("\nRelated tests: None found")

    issues = result.get("potential_issues", [])
    if issues:
        print("\nPotential issues:")
        for issue in issues[:5]:
            print("  Line %s: %s (%s)" % (issue.get("line", "?"), issue.get("message", "?"), issue.get("type", "?")))
    return 0


def cmd_review_coach(a):
    """Get code review feedback."""
    root, _ = C.need_repo()
    from . import review_coach_engine as RCE

    result = RCE.review_changes(a.base or "main", root)

    if a.json:
        _print(result)
        return 0

    if result.get("error"):
        print("Error: %s" % result["error"])
        return 1

    if result.get("message"):
        print(result["message"])
        return 0

    print("Files reviewed: %d" % len(result.get("files_reviewed", [])))
    print("Risk level: %s" % result.get("risk_level", "READY_TO_REVIEW"))

    counts = result.get("counts", {})
    print("\nCounts:")
    print("  Critical: %d" % counts.get("critical", 0))
    print("  High: %d" % counts.get("high", 0))
    print("  Medium: %d" % counts.get("medium", 0))
    print("  Low: %d" % counts.get("low", 0))

    issues = result.get("issues", [])
    if issues:
        print("\nIssues:")
        for issue in issues[:10]:
            f = issue.get("file", "")
            ln = issue.get("line", "?")
            loc = "%s:%s" % (f, ln) if f else "Line %s" % ln
            print("  [%s] %s: %s" % (issue.get("severity", "?"), loc, issue.get("message", "?")))
            if issue.get("suggestion"):
                print("    -> %s" % issue["suggestion"])
    return 0


def cmd_suggest_tests(a):
    """Suggest tests for a file."""
    root, _ = C.need_repo()
    from . import test_suggester_engine as TSE

    result = TSE.suggest_tests(a.file, root)

    if a.json:
        _print(result)
        return 0

    if result.get("error"):
        print("Error: %s" % result["error"])
        return 1

    print("File: %s" % result["file"])
    print("Language: %s" % result.get("language", "unknown"))

    funcs = result.get("functions", [])
    classes = result.get("classes", [])
    print("\nDefinitions:")
    print("  Functions: %d" % len(funcs))
    print("  Classes: %d" % len(classes))

    suggestions = result.get("suggested_tests", [])
    print("\nSuggested tests (%d):" % len(suggestions))
    for s in suggestions[:10]:
        print("  Priority %d: %s" % (s.get("priority", "?"), s.get("test_name", "?")))
        if s.get("reason"):
            print("    (%s)" % s["reason"])

    summary = result.get("priority_summary", {})
    print("\nSummary:")
    print("  Must have: %d" % summary.get("priority_1_must_have", 0))
    print("  Should have: %d" % summary.get("priority_2_should_have", 0))
    print("  Nice to have: %d" % summary.get("priority_3_nice_to_have", 0))

    related = result.get("related_tests", [])
    if related:
        print("\nExisting test files to add to:")
        for t in related[:5]:
            print("  %s" % t)
    return 0


def _sonar_print(res, limit=40):
    gate = {"OK": "passed", "ERROR": "FAILED", "WARN": "warning"}.get(res.get("gate"), res.get("gate") or "unknown")
    m = res.get("measures") or {}
    print("SonarQube (local): quality gate %s · %s bugs, %s vulnerabilities, %s code smells, %s hotspots, %s%% "
          "duplication" % (gate, m.get("bugs", "?"), m.get("vulnerabilities", "?"), m.get("code_smells", "?"),
                           m.get("security_hotspots", "?"), m.get("duplicated_lines_density", "?")))
    for c in res.get("conditions") or []:
        if c.get("status") == "ERROR":
            print("  gate condition failed: %s = %s (limit %s %s)" % (c["metricKey"], c.get("actualValue"),
                                                                      c.get("comparator"), c.get("errorThreshold")))
    print("On your change (%d changed file(s) against %s): %d issue(s)" % (
        res.get("changed_files", 0), (res.get("base") or "?")[:12], res.get("mine", 0)))
    for r in [r for r in res.get("issues") or [] if r["mine"]][:limit]:
        print("  %s:%s  %s %s  %s  [%s]" % (r["path"], r.get("line") or "-", r.get("severity"), r.get("kind"),
                                            r.get("message"), r.get("rule")))
    print("Everything: %s" % res.get("url"))


def _sonar_blocking(res):
    """What fails `lfg sonar scan`: a bug, vulnerability or hotspot, or a major-or-worse issue, on changed lines."""
    return [r for r in res.get("issues") or [] if r["mine"] and (
        r.get("kind") in ("BUG", "VULNERABILITY", "SECURITY_HOTSPOT") or
        str(r.get("severity")) in ("BLOCKER", "CRITICAL", "MAJOR", "HIGH"))]


def cmd_sonar(a):
    from . import sonar as SQ
    try:
        if a.action == "setup":
            out = SQ.setup(log=lambda m: print(m))
            print("SonarQube is %s at %s. `lfg sonar login` shows the admin password." % (out["state"], out["url"]))
            return 0
        if a.action == "status":
            st = SQ.server_state()
            print("SonarQube: %s at %s%s" % (st, SQ.URL, "" if SQ.creds().get("token") else
                                             " (not set up: lfg add sonarqube)"))
            return 0 if st == "up" else 1
        if a.action == "login":
            c = SQ.creds()
            if not c.get("password"):
                C.die("not set up yet: lfg add sonarqube", 1)
            print("%s\nuser: %s\npassword: %s" % (SQ.URL, c["user"], c["password"]))
            return 0
        if a.action == "stop":
            return 0 if SQ.stop() else 1
        if a.action == "remove":
            _print(SQ.remove(volumes=a.data))
            return 0
        root, rid = C.need_repo()
        if a.action == "cloud":
            res = SQ.cloud(root, a.base or "HEAD")
            if a.json:
                _print(res)
            elif not res or not res.get("found"):
                print("No SonarCloud check on %s (not pushed yet, or the repo doesn't use SonarCloud)."
                      % ((res or {}).get("sha") or "HEAD")[:12])
            else:
                verdict = res.get("conclusion") or res.get("status")
                print("SonarCloud on %s: %s%s\n%s\n%s" % (res["sha"][:12], verdict,
                                                         " - " + res["title"] if res.get("title") else "",
                                                         res.get("summary") or "", res.get("url") or ""))
            return 0
        res = SQ.scan(rid, root, base=a.base, log=lambda m: print(m)) if a.action == "scan" else SQ.last(rid)
        if not res:
            C.die("no scan yet: lfg sonar scan", 1)
        if a.json:
            _print(res)
        else:
            _sonar_print(res)
        return 1 if a.action == "scan" and _sonar_blocking(res) else 0
    except SQ.Problem as e:
        C.die(str(e), 2)


def cmd_omnigraph(a):
    from . import omnigraph as OG
    if a.action in ("serve", "mcp") and not a.name:
        C.die("usage: lfg omnigraph %s <%s>" % (a.action, "|".join(OG.cfg()["graphs"])), 2)
    if a.action == "serve":
        return OG.serve(a.name)
    if a.action == "mcp":
        return OG.mcp(a.name)
    if a.action == "restart":
        names = [a.name] if a.name else list(OG.cfg()["graphs"])
        return 0 if all(OG.restart(n) for n in names) else 1
    if a.action == "setup":
        out = OG.setup(launchd=not a.no_launchd)
    else:
        out = OG.status()
    if a.json:
        _print(out)
    elif a.action == "setup":
        for n, r in out.items():
            print("%-13s graph=%-6s %s  %s%s%s" % (n, r["graph"], r["url"], r["apply"],
                                               "" if "ready" not in r else ("  ready" if r["ready"] else "  NOT READY"),
                                               "" if "mcp" not in r else "  mcp: %s" % r["mcp"]))
            if r.get("hint"):
                print("  " + r["hint"])
    else:
        print("omnigraph: %s" % out["installed"])
        for n, r in out["graphs"].items():
            print("%-13s graph=%-6s %s  created=%s launchd=%s ready=%s mcp=%s" % (
                n, r["graph"], r["url"], r["created"], r["launchd"], r["ready"], r["mcp"]))
    if a.action == "setup":
        return 0 if all(r.get("ready", True) for r in out.values()) else 1
    return 0 if all(r["ready"] for r in out["graphs"].values()) else 1


def cmd_vendor(a):
    d = C.lfg_path("vendor", "mattpocock-skills")
    pin = C.read_json(C.lfg_path("vendor", "pin.json"), {}) or {}
    if a.action == "status":
        head = C.run(["git", "-C", d, "rev-parse", "HEAD"]).stdout.strip() if os.path.isdir(d) else None
        print("vendored mattpocock/skills (MIT, © 2026 Matt Pocock): %s, pinned %s" % (head or "not synced",
                                                                                      pin.get("commit", "none")))
        return 0
    if not os.path.isdir(d):
        C.ensure_dir(os.path.dirname(d))
        cp = C.run(["git", "clone", "-q", VENDOR_REPO, d], timeout=300)
        if cp.returncode:
            C.die(cp.stderr.strip(), 1)
    else:
        C.run(["git", "-C", d, "fetch", "-q", "origin"], timeout=300)
    if a.action == "sync" and pin.get("commit"):
        C.run(["git", "-C", d, "checkout", "-q", pin["commit"]])
    else:
        latest = C.run(["git", "-C", d, "rev-parse", "origin/HEAD"]).stdout.strip()
        if pin.get("commit") and latest != pin["commit"]:
            print(C.run(["git", "-C", d, "diff", "--stat", pin["commit"], latest]).stdout)
        C.run(["git", "-C", d, "checkout", "-q", latest])
        C.write_json(C.lfg_path("vendor", "pin.json"), {"commit": latest, "ts": C.now_iso()})
        print("pinned %s. Review the upstream changes above before adapting them into LFG skills." % latest)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="lfg", description="LFG: an engineering pipeline for Claude Code. Start with "
                                "`lfg setup`, then `lfg enable` in a repo.")
    sp = p.add_subparsers(dest="cmd")
    sp.add_parser("version")
    su = sp.add_parser("setup", help="install or update LFG: shows the plan first, changes nothing until you agree")
    su.add_argument("--packs", help="comma list of extra packs: security,shipcheck,pentest,knowledge,linear,headroom")
    su.add_argument("--here", action="store_true", help="also turn LFG on in the current repo")
    su.add_argument("--everywhere", action="store_true", help="turn LFG on in every repo (not recommended)")
    su.add_argument("--migrate", action="store_true",
                    help="also undo what an older LFG changed machine-wide (CLAUDE.md block, MCP servers, Headroom)")
    su.add_argument("--no-migrate", action="store_true", help=argparse.SUPPRESS)  # now the default
    su.add_argument("--dry-run", action="store_true", help="only show the plan")
    su.add_argument("--yes", "-y", action="store_true", help="apply without asking")
    su.add_argument("--json", action="store_true")
    for name, hlp in (("enable", "turn LFG on in this repo"), ("disable", "turn LFG off in this repo and undo "
                                                                          "what enable changed")):
        en = sp.add_parser(name, help=hlp)
        en.add_argument("path", nargs="?")
        en.add_argument("--everywhere", action="store_true", help="every repo (machine-wide plugin setting)")
        if name == "enable":
            en.add_argument("--hardened", action="store_true", help="also add deny rules behind the guard")
    pk = sp.add_parser("packs", help="optional feature packs: list, add <name>, remove <name>")
    pk.add_argument("action", choices=["list", "add", "remove"], nargs="?", default="list")
    pk.add_argument("name", nargs="?")
    pk.add_argument("--yes", "-y", action="store_true")
    pk.add_argument("--no-scripts", action="store_true", help="never run a curl | bash installer (Strix)")
    pk.add_argument("--json", action="store_true")
    for alias in ("add", "remove"):
        ad = sp.add_parser(alias, help="%s a feature pack (same as `lfg packs %s`)" % (alias, alias))
        ad.add_argument("name")
        ad.add_argument("--yes", "-y", action="store_true")
        ad.add_argument("--no-scripts", action="store_true")
        ad.add_argument("--json", action="store_true")
    ch = sp.add_parser("changes", help="what LFG changed outside ~/.lfg; `lfg changes undo <id>` reverts one")
    ch.add_argument("action", choices=["list", "undo"], nargs="?", default="list")
    ch.add_argument("id", nargs="?")
    ch.add_argument("--json", action="store_true")
    un = sp.add_parser("uninstall", help="undo every change LFG made and remove ~/.lfg")
    un.add_argument("--dry-run", action="store_true")
    un.add_argument("--keep-data", action="store_true", help="keep ~/.lfg (runs, graphs bookkeeping, config)")
    un.add_argument("--yes", "-y", action="store_true")
    dc = sp.add_parser("dictate", help="LFG Dictate: status or restart (turn it on with `lfg add dictate`)")
    dc.add_argument("action", choices=["status", "restart", "cleanup", "insert", "shortcut"], nargs="?",
                    default="status", help="cleanup on|off · insert paste|type · shortcut %s" % "|".join(
                        ["option+space", "right_option", "fn", "ctrl+space", "cmd+shift+space"]))
    dc.add_argument("value", nargs="?")
    dc.add_argument("--json", action="store_true")
    mc = sp.add_parser("mcp", help="(used by the plugin) start one of LFG's MCP servers")
    mc.add_argument("name")
    d = sp.add_parser("doctor")
    d.add_argument("--selftest", action="store_true")
    i = sp.add_parser("init")
    i.add_argument("--rebuild", action="store_true")
    g = sp.add_parser("graphs")
    g.add_argument("action", choices=["ensure", "status", "docs"],
                   help="ensure: sync now; status: fresh/stale; docs: regenerate wikis, call-flow and playbooks")
    for f in ("--background", "--allow-stale", "--json", "--quiet", "--rebuild"):
        g.add_argument(f, action="store_true")
    r = sp.add_parser("run")
    r.add_argument("action", choices=["new", "path", "scratch", "list", "set", "use", "skip", "unskip", "doing", "done",
                                      "merge", "review-stamp", "review-status"],
                   help="scratch: this machine's folder for the current run (/build's ticket worktrees); "
                        "use: make a run current (taking over a teammate's); "
                        "merge <from-run> [<into-run>]: move a duplicate run's files into another (default: current); "
                        "review-stamp: record in 06-review.json the checks and commit it was written against; "
                        "review-status: exit 1 when the review was written on red checks and commits landed since")
    r.add_argument("arg", nargs="?")
    r.add_argument("more", nargs="*", help="set: more key=value pairs; skip: why the step is left out")
    r.add_argument("--force", action="store_true", help="set: allow lowering the lane (only on the user's word)")
    kn = sp.add_parser("knowledge", help="the repo's shared knowledge in .lfg/ (sync with dev-graph, migrate); "
                                         "tag a saved decision or lesson with its repo, feature or topic")
    kn.add_argument("action", choices=["sync", "status", "migrate", "tag"])
    kn.add_argument("slug", nargs="?", help="tag: the item's slug (dev-graph Decision or Learning)")
    kn.add_argument("--repo", help="tag")
    kn.add_argument("--feature", help="tag")
    kn.add_argument("--topic", choices=["setup", "gotcha", "incident_review", "retro", "hindsight", ""], help="tag")
    kn.add_argument("--dry-run", action="store_true", help="migrate: only say what would move")
    kn.add_argument("--take-main-nodes", action="store_true",
                    help="migrate: also copy every Decision, Learning, ... on dev-graph's main into this repo's files")
    kn.add_argument("--json", action="store_true")
    kn.add_argument("--quiet", action="store_true")
    wt = sp.add_parser("worktree", help="work on another branch in its own folder (shares this repo's graphs)")
    wt.add_argument("action", choices=["new", "list", "remove", "merge"])
    wt.add_argument("name", nargs="?", help="new: branch; remove/merge: folder name or branch")
    wt.add_argument("--from", dest="base", help="new: start a new branch from this ref (default HEAD)")
    wt.add_argument("--into", help="merge: the branch to merge into (default: the one it was forked from)")
    wt.add_argument("--all", action="store_true", help="merge: every LFG worktree forked from --into")
    wt.add_argument("--remove", action="store_true", help="merge: then remove the worktree and its merged branch")
    wt.add_argument("--merge-commit", action="store_true",
                    help="merge: allow a merge commit when the base moved on (default: fast-forward only)")
    iss = sp.add_parser("issue", help="mirror the run's issue into dev-graph (the Issues page)")
    iss.add_argument("action", choices=["sync", "show", "sync-tasks", "sync-brief"],
                     help="sync-tasks: one Issue per task in the current run's tasks.json (text, checks, done); "
                          "sync-brief: the brief's Problem and Acceptance criteria onto the run's Issue")
    iss.add_argument("key", nargs="?", help="tracker id (ACME-4225) or a short title for an idea")
    iss.add_argument("--title")
    iss.add_argument("--type", choices=["bug", "feature", "task", "chore", "question", "risk"])
    iss.add_argument("--status", choices=["backlog", "todo", "in_progress", "needs_review", "hold", "done",
                                          "canceled", "duplicate"])
    iss.add_argument("--priority", type=int, choices=range(0, 5))
    iss.add_argument("--description")
    iss.add_argument("--criteria", help="acceptance criteria: what done looks like")
    iss.add_argument("--json", action="store_true")
    ru = sp.add_parser("rule")
    ru.add_argument("name")
    rp = sp.add_parser("repo")
    rp.add_argument("action", choices=["docs", "knowledge", "id", "root", "graph"],
                    help="root: main checkout (also from a worktree); graph: graphify graph.json path")
    rp.add_argument("--branch", nargs="?", const="", default=None, metavar="NAME",
                    help="docs: the folder for docs about this branch's work (the checked-out branch by default)")
    la = sp.add_parser("lane")
    la.add_argument("--json", action="store_true")
    ga = sp.add_parser("gate")
    ga.add_argument("--json", action="store_true")
    ga.add_argument("--fix", action="store_true")
    ga.add_argument("--affected", action="store_true")
    ga.add_argument("--only", help="comma list of lint,types,test,build")
    ci = sp.add_parser("ci-local")
    ci.add_argument("--list", action="store_true")
    ci.add_argument("--affected", action="store_true",
                    help="only workflows whose path filters match this branch's changed files")
    ci.add_argument("--json", action="store_true")
    se = sp.add_parser("secure")
    se.add_argument("target", nargs="?")
    se.add_argument("--json", action="store_true")
    se.add_argument("--offline", action="store_true")
    pe = sp.add_parser("pentest")
    pe.add_argument("--target")
    pe.add_argument("--mode", choices=["quick", "standard", "deep"], default="quick")
    pe.add_argument("--model")
    pe.add_argument("--preflight", action="store_true", help="only run the offline preflight")
    pe.add_argument("--json", action="store_true")
    sc = sp.add_parser("shipcheck")
    sc.add_argument("--cleanup", action="store_true")
    sc.add_argument("--json", action="store_true")
    sp.add_parser("watch")
    sp.add_parser("playbooks", help="write onboarding/landmines/test-gap playbooks from the graphs")
    u = sp.add_parser("ui")
    u.add_argument("--port", type=int)
    u.add_argument("--no-open", action="store_true", help="don't open the browser (Settings stay locked)")
    u.add_argument("--unlock", action="store_true", help="open the running dashboard with editing unlocked")
    u.add_argument("--browser", help="with --unlock: which browser app, e.g. \"Google Chrome\" (default: your default)")
    cm = sp.add_parser("claudemd", help="show ~/.claude/CLAUDE.md, or remove the block older LFG versions added")
    cm.add_argument("action", choices=["show", "remove-legacy"])
    fb = sp.add_parser("feedback")
    fb.add_argument("action", choices=["add"])
    fb.add_argument("finding")
    fb.add_argument("verdict", choices=["accept", "reject"])
    fb.add_argument("--note")
    rv = sp.add_parser("review", help="PR reviews: context, save, show, list, mark, threads, remember, pass; "
                                      "post and run are yours")
    rv.add_argument("action", choices=["context", "save", "show", "list", "mark", "post", "threads", "others", "run",
                                       "sessions", "import", "fix", "remember", "pass", "passes"])
    rv.add_argument("pr", nargs="?", help="PR number (repo from this checkout), owner/repo#12 or a PR URL")
    rv.add_argument("ids", nargs="*", help="mark: finding ids, e.g. 1.2 1.4")
    st = rv.add_mutually_exclusive_group()
    for s_ in ("keep", "drop", "pending"):
        st.add_argument("--" + s_, dest="status", action="store_const", const=s_)
    rv.add_argument("--to", choices=["dev-graph", "second-brain"],
                    help="remember: where to save what the finding's discussion settled (always your choice)")
    rv.add_argument("--scope", choices=["pr", "repo", "all"],
                    help="pass: don't flag this again on this PR only, on every PR in the repo, or in every repo")
    rv.add_argument("--note", help="remember: the conclusion in your words; pass: why you passed on it")
    rv.add_argument("--remove", metavar="ID", help="passes: take that pass off the list (ids: `lfg review passes`)")
    rv.add_argument("--body", help="mark: new comment text; post: text above the inline comments")
    rv.add_argument("--body-file")
    rv.add_argument("--file", help="save: findings JSON (default: stdin); import: the session or log to import")
    rv.add_argument("--ticket", help="save/run: the Linear ticket the PR belongs to; list: only that ticket")
    rv.add_argument("--event", choices=["approve", "request-changes", "comment"])
    rv.add_argument("--dry-run", action="store_true", help="post: show what would be sent")
    rv.add_argument("--fresh", action="store_true", help="run: a full new review, not a re-review")
    rv.add_argument("--fresh-eyes", action="store_true",
                    help="run: a full review that never sees earlier reviews or anyone else's comments")
    rv.add_argument("--model", help="run: the model to review with (default: Settings → Model for reviews)")
    rv.add_argument("--method", help="run: this review's method, a JSON list of files or folders (default: Settings)")
    rv.add_argument("--notes", help="run: what to look into on top of the method: an angle, context, a worry")
    rv.add_argument("--with", dest="with_", action="append", metavar="PR",
                    help="run: another PR to review in the same session, e.g. the frontend for a backend PR")
    rv.add_argument("--json", action="store_true")
    pf = sp.add_parser("prefs", help="your rules for Claude: defaults, per-session changes, hooks that enforce them")
    pf.add_argument("action", nargs="?", default="list",
                    choices=["list", "set", "clear", "remind", "install", "status", "hook"])
    pf.add_argument("id", nargs="?",
                    help="set: the preference; remind: a session id; hook: session-start|prompt|pre-tool|stop")
    pf.add_argument("value", nargs="?", help="set: on/off, or one of the choices")
    pf.add_argument("--session", help="one session (its id from lfg sessions); default: the defaults")
    pf.add_argument("--by-user", action="store_true", help="allow loosening (your own terminal only)")
    cr = sp.add_parser("corrections", help="what you correct Claude on, queued for you to turn into rules")
    cr.add_argument("action", nargs="?", default="list",
                    choices=["list", "show", "add", "approve", "merge", "discard", "brain", "rules", "on", "off",
                             "status"])
    cr.add_argument("args", nargs="*", help="show/approve/discard: the id(s); merge: id and rule id; add: the words")
    cr.add_argument("--did", help="add: what Claude had done")
    cr.add_argument("--note", help="add: the lesson, one sentence")
    cr.add_argument("--text", help="approve/merge: the rule, what Claude should do from now on")
    cr.add_argument("--title", help="approve: a short name for the rule")
    cr.add_argument("--why", help="approve/merge: why it matters, told to Claude with the rule")
    cr.add_argument("--example", help="approve/merge: a real time it went wrong, told to Claude with the rule")
    cr.add_argument("--scope", default="global", choices=["global", "project"],
                    help="approve: every repo, or only the repo it was said in")
    cr.add_argument("--all", action="store_true", help="list: resolved ones too")
    cr.add_argument("--json", action="store_true")
    pl = sp.add_parser("plugins", help="Claude Code plugins: list (and search), install, enable, disable, uninstall")
    pl.add_argument("action", nargs="?", default="list", choices=["list", "install", "enable", "disable", "uninstall"])
    pl.add_argument("id", nargs="*", help="name@marketplace; list: words to search the marketplaces for")
    pl.add_argument("--json", action="store_true")
    up = sp.add_parser("update", help="is there newer LFG (your fork, the original project)? apply installs it; fix "
                                      "has Claude fix a stopped update, then applies")
    up.add_argument("action", nargs="?", default="check", choices=["check", "apply", "fix"])
    up.add_argument("--json", action="store_true")
    ss = sp.add_parser("sessions", help="every Claude Code session on this machine, with the command that resumes it")
    ss.add_argument("action", nargs="?", default="list", choices=["list", "name", "folder", "skill", "run"])
    ss.add_argument("id", nargs="?", help="name/folder/skill: the session id; run: the run id")
    ss.add_argument("value", nargs="*", help="skill: /skill-name then anything to tell it; "
                    "name: your name for it; folder: your group for it, LFG only, nothing on "
                    "disk moves (empty takes it out)")
    ss.add_argument("--times", type=int, default=1, help="skill: run it this many times in a row (max 10)")
    ss.add_argument("--until-clean", action="store_true", help="skill: stop early once a pass changes nothing")
    ss.add_argument("--mode", default="auto", choices=["auto", "acceptEdits", "dontAsk"], help="skill: permissions")
    ss.add_argument("--model", help="skill: the model to run on (default: Claude Code's own)")
    ss.add_argument("--in-place", action="store_true", help="skill: add to the session itself, not a copy of it")
    ss.add_argument("--find", help="list: only sessions whose name, repo, branch, ticket or group has this")
    ss.add_argument("--days", type=int, help="list: only the last N days")
    ss.add_argument("--limit", type=int, default=30)
    ss.add_argument("--json", action="store_true")
    us = sp.add_parser("usage")
    us.add_argument("--json", action="store_true")
    ve = sp.add_parser("vendor")
    ve.add_argument("action", choices=["status", "sync", "update"])
    sq = sp.add_parser("sonar", help="local SonarQube: find what SonarCloud would fail, before you push")
    sq.add_argument("action", choices=["setup", "status", "scan", "issues", "cloud", "login", "stop", "remove"])
    sq.add_argument("--base", help="scan: what 'your change' is measured against (default: origin's default branch)"
                                   "; cloud: the commit to look up (default HEAD)")
    sq.add_argument("--data", action="store_true", help="remove: also delete the analysis data volumes")
    sq.add_argument("--json", action="store_true")
    og = sp.add_parser("omnigraph", help="local dev-graph + second-brain (setup, status, restart)")
    og.add_argument("action", choices=["setup", "status", "restart", "serve", "mcp"])
    og.add_argument("name", nargs="?", help="second-brain or dev-graph (serve/mcp/restart)")
    og.add_argument("--no-launchd", action="store_true", help="setup: don't install/start the login agents")
    og.add_argument("--json", action="store_true")
    hr = sp.add_parser("headroom", help="optional Headroom proxy (setup, status, restart, off)")
    hr.add_argument("action", choices=["setup", "status", "restart", "off", "serve"])
    hr.add_argument("--upstream", help="setup: where the proxy forwards (default: the previous ANTHROPIC_BASE_URL "
                                       "or api.anthropic.com)")
    hr.add_argument("--scope", choices=["repos", "everywhere"],
                    help="setup: route only repos where LFG is on (default) or every session")
    hr.add_argument("--json", action="store_true")
    # onboard: run wizard or set features non-interactively
    ob = sp.add_parser("onboard", help="pick LFG features (run without flags for interactive wizard)")
    ob.add_argument("--all", action="store_true", help="enable all features")
    ob.add_argument("--features", help="comma list of features: coding,reviews,security,knowledge,planning")
    ob.add_argument("--json", action="store_true")
    hs = sp.add_parser("hotspots", help="files that keep needing fixes (from git history)")
    hs.add_argument("--days", type=int, default=180)
    hs.add_argument("--limit", type=int, default=15)
    hs.add_argument("--json", action="store_true")
    wy = sp.add_parser("why", help="why code looks like this: the commits, issues and PRs behind a file or lines")
    wy.add_argument("target", help="file, file:LINE or file:START-END")
    wy.add_argument("--limit", type=int, default=15)
    wy.add_argument("--json", action="store_true")
    # explain5: explain code in plain English
    ex = sp.add_parser("explain5", help="explain code in plain English")
    ex.add_argument("file", help="file to explain")
    ex.add_argument("--json", action="store_true")
    # review-coach: pre-review code feedback
    rc = sp.add_parser("review-coach", help="get code review feedback before submitting")
    rc.add_argument("--base", help="base branch for comparison (default: main)")
    rc.add_argument("--json", action="store_true")
    # suggest-tests: suggest tests for code changes
    st = sp.add_parser("suggest-tests", help="suggest tests based on code changes")
    st.add_argument("file", help="file to analyze")
    st.add_argument("--json", action="store_true")
    h = sp.add_parser("hook")
    h.add_argument("event")
    a = p.parse_args(argv)
    if a.cmd is None:
        p.print_help()
        return 2
    if a.cmd == "version":
        print("lfg %s (MIT, by %s)" % (C.VERSION, C.AUTHOR))
        return 0
    if a.cmd == "hook":
        from . import hooks
        return hooks.main(a.event)
    if a.cmd == "doctor":
        return doctor(a.selftest)
    if a.cmd == "ui":
        from . import ui
        port = a.port or C.config()["ui"]["port"]
        if a.unlock:
            if ui.open_editor(port, a.browser):
                return 0
            C.die("couldn't open %s" % (a.browser or "the browser"), 1)
        ui.serve(port, open_browser=not a.no_open)
        return 0
    if a.cmd == "claudemd":
        from . import settings as S
        if a.action == "show":
            print(S.claude_md()["text"], end="")
            return 0
        r = S.remove_claude_md_section()
        print("%s: %s" % (r["path"], "LFG block removed" if r["removed"] else "you edited the LFG block, so it was "
                          "left as is" if r.get("edited") else "no LFG block"))
        return 0
    if a.cmd == "dictate":
        from . import dictate as DI
        if a.action == "restart":
            return 0 if DI.restart() else 1
        if a.action in ("cleanup", "insert", "shortcut"):
            from . import settings as S
            try:
                r = DI.set_option(a.action, a.value)
            except S.Invalid as e:
                C.die(str(e), 2)
            print("Dictate %s: %s%s" % (a.action, a.value, "".join("\n  " + n for n in r.get("notes", []))))
            return 0
        st = DI.status()
        if a.json:
            _print(st)
        elif not st["installed"]:
            print("Dictate is off. Turn it on with `lfg add dictate` (downloads about 90 MB, all on-device).")
        else:
            print("Dictate: %s · hold %s to talk, double-tap for hands-free · %s%s%s" % (
                "running" if st["agent"] else "not running", st["shortcut_label"],
                "types" if st["insert"] == "type" else "pastes", " · cleans up with Claude" if st["cleanup"] else "",
                " · %s" % st["error"] if st["error"] else ""))
            if st["last"]:
                print("Last dictation: %s into %s (focused: %s)" % (
                    {"paste": "copied and pasted", "type": "copied and typed", "clipboard": "copied"}.get(
                        st["last"].get("went"), "?"), st["last"].get("app") or "?", st["last"].get("focus")))
        return 0 if not st["installed"] or st["agent"] else 1
    if a.cmd == "mcp":
        from . import mcp
        return mcp.serve(a.name)
    if a.cmd in ("add", "remove"):
        a.action = a.cmd
        return cmd_packs(a)
    return {"init": cmd_init, "graphs": cmd_graphs, "run": cmd_run, "rule": cmd_rule, "repo": cmd_repo,
            "hotspots": cmd_hotspots, "why": cmd_why,
            "lane": cmd_lane, "gate": cmd_gate, "ci-local": cmd_ci_local, "secure": cmd_secure,
            "pentest": cmd_pentest, "shipcheck": cmd_shipcheck, "watch": cmd_watch, "feedback": cmd_feedback,
            "usage": cmd_usage, "sessions": cmd_sessions, "update": cmd_update, "knowledge": cmd_knowledge,
            "prefs": cmd_prefs,
            "plugins": cmd_plugins,
            "corrections": cmd_corrections,
            "vendor": cmd_vendor,
            "omnigraph": cmd_omnigraph, "sonar": cmd_sonar,
            "headroom": cmd_headroom,
            "playbooks": cmd_playbooks, "review": cmd_review, "issue": cmd_issue, "worktree": cmd_worktree,
            "setup": cmd_setup, "enable": cmd_enable, "disable": cmd_disable, "packs": cmd_packs,
            "changes": cmd_changes, "uninstall": cmd_uninstall, "onboard": cmd_onboard, "explain5": cmd_explain5,
            "review-coach": cmd_review_coach, "suggest-tests": cmd_suggest_tests}[a.cmd](a)
