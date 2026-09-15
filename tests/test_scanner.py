import socket
from pathlib import Path

from filewizard.scanner import iter_files


def test_skips_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    found = list(iter_files(tmp_path))
    assert real in found
    assert link not in found


def test_does_not_follow_symlink_dirs_or_cycles(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    (a / "file.txt").write_text("x", encoding="utf-8")
    # symlink that would create a cycle if followed
    (a / "loop").symlink_to(tmp_path)

    found = list(iter_files(tmp_path))
    assert a / "file.txt" in found
    # Should not explode and should not walk through loop forever
    assert len(found) == 1


def test_hidden_files_default_off(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("v", encoding="utf-8")
    (tmp_path / ".secret.txt").write_text("s", encoding="utf-8")
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "inside.txt").write_text("i", encoding="utf-8")

    found = {p.name for p in iter_files(tmp_path)}
    assert found == {"visible.txt"}

    found_all = {p.name for p in iter_files(tmp_path, include_hidden=True)}
    assert "visible.txt" in found_all
    assert ".secret.txt" in found_all
    assert "inside.txt" in found_all


def test_unicode_paths(tmp_path: Path) -> None:
    d = tmp_path / "carpeta_ñoño_文件"
    d.mkdir()
    f = d / "factura_áéí_日本.txt"
    f.write_text("ok", encoding="utf-8")

    found = list(iter_files(tmp_path))
    assert f in found


def test_long_filename(tmp_path: Path) -> None:
    # Stay under typical 255-byte name limit
    name = ("a" * 200) + ".txt"
    f = tmp_path / name
    f.write_text("x", encoding="utf-8")
    found = list(iter_files(tmp_path))
    assert f in found


def test_skips_socket_if_present(tmp_path: Path) -> None:
    sock_path = tmp_path / "s.sock"
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(sock_path))
    except OSError:
        # Platform may not support unix sockets in tmp
        return
    try:
        (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
        found = list(iter_files(tmp_path))
        assert sock_path not in found
        assert any(p.name == "ok.txt" for p in found)
    finally:
        s.close()
        if sock_path.exists():
            sock_path.unlink()


def test_permission_denied_dir_is_skipped(tmp_path: Path) -> None:
    open_dir = tmp_path / "open"
    closed = tmp_path / "closed"
    open_dir.mkdir()
    closed.mkdir()
    (open_dir / "a.txt").write_text("a", encoding="utf-8")
    (closed / "b.txt").write_text("b", encoding="utf-8")

    closed.chmod(0o000)
    try:
        found = list(iter_files(tmp_path))
        # Must not raise; open file should still be found
        assert open_dir / "a.txt" in found
    finally:
        closed.chmod(0o755)


def test_file_vanishes_during_walk_does_not_break(tmp_path: Path) -> None:
    # Hard to simulate mid-yield reliably; ensure empty / vanishing root is fine
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list(iter_files(empty)) == []

    missing = tmp_path / "missing"
    assert list(iter_files(missing)) == []


def test_ignores_tooling_dirs(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
    git = tmp_path / ".git"
    git.mkdir()
    # even with include_hidden, .git is ignored as tooling dir
    (git / "config").write_text("g", encoding="utf-8")
    node = tmp_path / "node_modules"
    node.mkdir()
    (node / "pkg.js").write_text("p", encoding="utf-8")

    found = list(iter_files(tmp_path, include_hidden=True))
    names = {p.name for p in found}
    assert "ok.txt" in names
    assert "config" not in names
    assert "pkg.js" not in names
