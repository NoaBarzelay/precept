from precept.safety import atomic_write_text


def test_atomic_write_creates_and_overwrites(tmp_path):
    p = tmp_path / "sub" / "f.txt"
    atomic_write_text(p, "one")
    assert p.read_text() == "one"
    atomic_write_text(p, "two")
    assert p.read_text() == "two"
    # no leftover temp files in the directory
    assert [x.name for x in p.parent.iterdir()] == ["f.txt"]
