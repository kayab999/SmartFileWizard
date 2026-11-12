from pathlib import Path

import pytest

import yaml

from filewizard.cancel import CancelToken
from filewizard.journal import Journal
from filewizard.models import Action, Condition, Rule, RuleSet
from filewizard.watch import (
    ActiveWatch,
    WatchConfig,
    WatchError,
    WatcherLockError,
    add_active_watch,
    changed_paths,
    retry_watch_paths,
    load_active_watches,
    remove_active_watch,
    snapshot,
    watch_once,
    watcher_lock,
)


def _write_rules(dir_: Path) -> None:
    ruleset = RuleSet(
        version=1,
        rules=[
            Rule(
                id="txt",
                name="Texto",
                priority=10,
                when=Condition(extensions=["txt"]),
                then=Action(move_to=str(dir_ / "txt")),
            ),
        ],
    )
    dir_.joinpath("rules.yaml").write_text(
        yaml.safe_dump(
            ruleset.model_dump(mode="python", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def test_watch_config_requires_preset_or_rules() -> None:
    with pytest.raises(WatchError):
        WatchConfig(source=Path("/tmp"), preset=None, rules=None)
    with pytest.raises(WatchError):
        WatchConfig(source=Path("/tmp"), preset="p", rules=Path("r.yaml"))


def test_watch_once_dry_run_plans_only(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "note.txt").write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)

    cfg = WatchConfig(
        source=src,
        rules=tmp_path / "rules.yaml",
        dry_run=True,
        state_dir=tmp_path / "state",
    )

    ops, scanned = watch_once(cfg)

    assert scanned == 1
    assert len(ops) == 1
    assert ops[0].status == "planned"
    assert not (tmp_path / "txt" / "note.txt").exists()
    assert (src / "note.txt").exists()


def test_watch_once_execute_moves_and_journals(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "note.txt").write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)

    state = tmp_path / "state"
    cfg = WatchConfig(
        source=src,
        rules=tmp_path / "rules.yaml",
        dry_run=False,
        state_dir=state,
    )

    ops, scanned = watch_once(cfg)

    assert scanned == 1
    assert len(ops) == 1
    assert ops[0].status == "done"
    assert not (src / "note.txt").exists()
    assert (tmp_path / "txt" / "note.txt").exists()

    with Journal(state / "journal.db") as journal:
        moves = journal.last_successful_moves(limit=10)
        assert any(
            row["destination"] == str(tmp_path / "txt" / "note.txt")
            and row["status"] == "done"
            for row in moves
        )


def test_watch_once_preset_error_clear(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    cfg = WatchConfig(
        source=src,
        preset="does-not-exist-xyz",
        dry_run=True,
        state_dir=tmp_path / "state",
    )
    with pytest.raises(WatchError):
        watch_once(cfg)


def test_interruptible_sleep_returns_on_cancel() -> None:
    import time

    from filewizard.watch import interruptible_sleep

    token = CancelToken()
    token.cancel()
    t0 = time.monotonic()
    interruptible_sleep(5.0, token, step=0.05)
    assert time.monotonic() - t0 < 1.0


def test_watch_loop_debounce_does_not_replan_unchanged(tmp_path: Path) -> None:
    """WP-0.6.2: a file that did not change is not re-planned next tick."""
    from filewizard.watch import watch_loop

    src = tmp_path / "in"
    src.mkdir()
    note = src / "note.txt"
    note.write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)

    cfg = WatchConfig(
        source=src,
        rules=tmp_path / "rules.yaml",
        dry_run=True,
        state_dir=tmp_path / "state",
    )

    planned_per_tick: list[int] = []
    token = CancelToken()

    def _on_tick(_tick: int, ops: list, _changed: int) -> None:
        planned_per_tick.append(len(ops))
        token.cancel()

    # first tick: new file -> planned (on_tick stops the loop)
    watch_loop(cfg, interval=1, cancel=token, on_tick=_on_tick)
    assert planned_per_tick[0] == 1

    # second tick with no changes -> nothing planned
    token.reset()
    watch_loop(cfg, interval=1, cancel=token, on_tick=_on_tick)
    assert planned_per_tick[1] == 0

    assert len(planned_per_tick) == 2


def test_watch_loop_replans_changed_file(tmp_path: Path) -> None:
    """A modified file gets planned again when its signature changes."""
    from filewizard.watch import watch_loop

    src = tmp_path / "in"
    src.mkdir()
    note = src / "note.txt"
    note.write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)

    cfg = WatchConfig(
        source=src,
        rules=tmp_path / "rules.yaml",
        dry_run=True,
        state_dir=tmp_path / "state",
    )

    planned_per_tick: list[int] = []
    token = CancelToken()

    def _on_tick(_tick: int, ops: list, _changed: int) -> None:
        planned_per_tick.append(len(ops))
        token.cancel()

    watch_loop(cfg, interval=1, cancel=token, on_tick=_on_tick)
    token.reset()

    # change the file content *and* force a different mtime
    note.write_text("hola de nuevo", encoding="utf-8")
    watch_loop(cfg, interval=1, cancel=token, on_tick=_on_tick)

    assert planned_per_tick[0] == 1
    assert planned_per_tick[1] == 1


def test_watch_snapshot_and_changed_paths(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    snap1 = snapshot(src)
    assert len(snap1) == 1

    # same content, same signature -> no change
    assert changed_paths(
        {str(p): [sig[0], sig[1]] for p, sig in snap1.items()},
        snap1,
    ) == []

    # modify
    (src / "a.txt").write_text("b" * 200, encoding="utf-8")
    snap2 = snapshot(src)
    changed = changed_paths(
        {str(p): [sig[0], sig[1]] for p, sig in snap1.items()},
        snap2,
    )
    assert len(changed) == 1


def test_watcher_lock_single_process_ok(tmp_path: Path) -> None:
    with watcher_lock(tmp_path / "state") as lock:
        assert lock.exists()


def test_watcher_lock_second_instance_fails(tmp_path: Path) -> None:
    state = tmp_path / "state"
    with watcher_lock(state):
        with pytest.raises(WatcherLockError):
            with watcher_lock(state):
                pass


def test_watch_once_respects_existing_lock(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "note.txt").write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)
    state = tmp_path / "state"
    cfg = WatchConfig(
        source=src,
        rules=tmp_path / "rules.yaml",
        dry_run=True,
        state_dir=state,
    )
    with watcher_lock(state):
        with pytest.raises(WatcherLockError):
            watch_once(cfg)


def test_watcher_lock_reclaims_stale(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    lock = state / "watch.lock"
    # pid that will not be alive (very large, out of pid space on Linux)
    lock.write_text("999999  \n", encoding="utf-8")
    with watcher_lock(state) as fresh:
        assert fresh == lock
        assert lock.read_text().strip() != "999999"


# --- active watch list (WP-0.6.3) -----------------------------------------


def test_active_watch_config_validation(tmp_path: Path) -> None:
    with pytest.raises(WatchError):
        ActiveWatch(name="x", source=tmp_path, preset=None, rules=None)
    with pytest.raises(WatchError):
        ActiveWatch(name="x", source=tmp_path, preset="p", rules=Path("r.yaml"))
    with pytest.raises(WatchError):
        ActiveWatch(name="", source=tmp_path, preset="p")
    with pytest.raises(WatchError):
        ActiveWatch(name="x", source=tmp_path, preset="p", interval_s="fast")


def test_active_watch_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    state = tmp_path / "state"

    add_active_watch(
        state,
        ActiveWatch(
            name="downloads",
            source=src,
            preset="images-cascade",
            dry_run=True,
            interval_s=60,
        ),
    )
    add_active_watch(
        state,
        ActiveWatch(
            name="shots",
            source=src,
            rules=tmp_path / "rules.yaml",
            dry_run=False,
            interval_s=30,
        ),
    )

    watches = load_active_watches(state)
    assert [w.name for w in watches] == ["downloads", "shots"]
    assert watches[0].preset == "images-cascade"
    assert watches[0].dry_run is True
    assert watches[1].rules == tmp_path / "rules.yaml"
    assert watches[1].interval_s == 30

    # overwrite requires flag
    with pytest.raises(WatchError):
        add_active_watch(
            state, ActiveWatch(name="downloads", source=src, preset="example")
        )
    add_active_watch(
        state,
        ActiveWatch(name="downloads", source=src, preset="example"),
        overwrite=True,
    )
    assert load_active_watches(state)[0].preset == "example"

    removed = remove_active_watch(state, "downloads")
    assert removed.name == "downloads"
    assert [w.name for w in load_active_watches(state)] == ["shots"]

    # file is valid YAML and persistent across loads
    text = (state / "active_watches.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert len(parsed["watches"]) == 1
    assert parsed["watches"][0]["source"] == str(src)


def test_active_watch_run_applies_a_watch(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "note.txt").write_text("hola", encoding="utf-8")
    _write_rules(tmp_path)
    state = tmp_path / "state"

    add_active_watch(
        state,
        ActiveWatch(
            name="auto",
            source=src,
            rules=tmp_path / "rules.yaml",
            dry_run=True,
        ),
    )

    cfg = load_active_watches(state)[0].to_watch_config(state)
    ops, scanned = watch_once(cfg)
    assert scanned == 1
    assert len(ops) == 1
    assert ops[0].status == "planned"
    assert (src / "note.txt").exists()


# ---- R9.1 Unit 2: retry_watch_paths tests ----

def _seed_state(state_dir, src, entries):
    import json
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {"sources": {str(src.resolve()): entries}}
    (state_dir / "watch_state.json").write_text(json.dumps(state))


def test_retry_watch_paths_existing_registered(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x")
    state_dir = tmp_path / "state"
    _seed_state(state_dir, src, {str(f.resolve()): [1, 2, 3, 4, 5, 3]})
    (state_dir / "watch_giveups.jsonl").write_text(
        '{"path": "%s", "attempts": 3}\n' % f.resolve()
    )
    res = retry_watch_paths(state_dir, [str(f)])
    assert res["reset"] == 1 and res["not_found"] == 0
    import json
    after = json.loads((state_dir / "watch_state.json").read_text())
    assert after["sources"][str(src.resolve())][str(f.resolve())][-1] == 1
    assert not (state_dir / "watch_giveups.jsonl").read_text().strip()


def test_retry_watch_paths_nonexistent(tmp_path: Path) -> None:

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "watch_state.json").write_text('{"sources": {}}')
    res = retry_watch_paths(state_dir, [str(tmp_path / "nope.txt")])
    assert res["reset"] == 0 and res["not_found"] == 1


def test_retry_watch_paths_unregistered(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "watch_state.json").write_text('{"sources": {}}')
    res = retry_watch_paths(state_dir, [str(f)])
    assert res["reset"] == 0 and res["not_found"] == 1


def test_retry_watch_paths_multiple_and_duplicates(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f1 = src / "a.txt"
    f1.write_text("x")
    f2 = src / "b.txt"
    f2.write_text("y")
    state_dir = tmp_path / "state"
    _seed_state(state_dir, src, {
        str(f1.resolve()): [1, 2, 3, 4, 5, 3],
        str(f2.resolve()): [1, 2, 3, 4, 5, 3],
    })
    res = retry_watch_paths(state_dir, [str(f1), str(f1), str(f2)])
    assert res["reset"] == 2
    assert res["targets"] == 2


def test_retry_watch_paths_persistence(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x")
    state_dir = tmp_path / "state"
    _seed_state(state_dir, src, {str(f.resolve()): [1, 2, 3, 4, 5, 3]})
    retry_watch_paths(state_dir, [str(f)])
    import json
    after = json.loads((state_dir / "watch_state.json").read_text())
    assert after["sources"][str(src.resolve())][str(f.resolve())][-1] == 1


def test_retry_watch_paths_malformed_giveups(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("x")
    state_dir = tmp_path / "state"
    _seed_state(state_dir, src, {str(f.resolve()): [1, 2, 3, 4, 5, 3]})
    (state_dir / "watch_giveups.jsonl").write_text(
        "not json\n" + '{"path": "%s", "attempts": 3}\n' % f.resolve()
    )
    retry_watch_paths(state_dir, [str(f)])
    content = (state_dir / "watch_giveups.jsonl").read_text()
    assert "not json" in content


def test_retry_watch_paths_does_not_touch_others(tmp_path: Path) -> None:

    src = tmp_path / "src"
    src.mkdir()
    f1 = src / "a.txt"
    f1.write_text("x")
    f2 = src / "b.txt"
    f2.write_text("y")
    state_dir = tmp_path / "state"
    _seed_state(state_dir, src, {
        str(f1.resolve()): [1, 2, 3, 4, 5, 3],
        str(f2.resolve()): [1, 2, 3, 4, 5, 2],
    })
    retry_watch_paths(state_dir, [str(f1)])
    import json
    after = json.loads((state_dir / "watch_state.json").read_text())
    assert after["sources"][str(src.resolve())][str(f1.resolve())][-1] == 1
    assert after["sources"][str(src.resolve())][str(f2.resolve())][-1] == 2


def test_retry_watch_paths_concurrency_lock(tmp_path: Path) -> None:
    from filewizard.watch import watcher_lock, WatcherLockError

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "watch_state.json").write_text('{"sources": {}}')
    with watcher_lock(state_dir):
        try:
            retry_watch_paths(state_dir, [str(tmp_path / "x.txt")])
            raised = False
        except WatcherLockError:
            raised = True
    assert raised


def test_retry_watch_paths_while_watcher_active(tmp_path: Path) -> None:
    """Real scenario: retry while watch_loop holds the lock raises
    WatcherLockError (not a traceback) and documents the contract."""
    import threading
    import time

    from filewizard.cancel import CancelToken
    from filewizard.watch import WatchConfig, WatcherLockError, retry_watch_paths, watch_loop

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []\n")
    cfg = WatchConfig(
        source=src, preset=None, rules=rules, dry_run=True,
        state_dir=state_dir, limit=None, profile=None,
        agent_features=None, allow_model_only=False,
    )

    cancel = CancelToken()
    t = threading.Thread(
        target=watch_loop, kwargs={"cfg": cfg, "interval": 10.0, "cancel": cancel}, daemon=True
    )
    t.start()
    time.sleep(0.5)
    try:
        raised = False
        try:
            retry_watch_paths(state_dir, [str(src / "a.txt")])
        except WatcherLockError:
            raised = True
        assert raised, "retry must not silently succeed while watcher holds the lock"
    finally:
        cancel.cancel()
        t.join(timeout=5.0)