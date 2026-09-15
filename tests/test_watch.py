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