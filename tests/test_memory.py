from chronicle.memory import Memory


def test_backdated_correction_cannot_change_earlier_known_state(tmp_path):
    m = Memory(tmp_path / "m.sqlite", "a")
    m.ingest(
        [
            {"id": "old", "observed_at": "2026-01-01", "text": "地点A；预算100。"},
            {"id": "new", "observed_at": "2026-01-15", "text": "更正，1月8日起地点B。"},
        ]
    )
    m.add_note("old", "地点A", "地点A", claim_key="place")
    m.add_note("old", "预算100", "预算100", claim_key="budget")
    m.add_note(
        "new",
        "地点B",
        "地点B",
        valid_from="2026-01-08",
        supersedes="old",
        claim_key="place",
    )
    # Query the SQL eligibility/append-only state without any fake embeddings/model.
    assert {x["id"] for x in m.sources("2026-01-12")} == {"old"}
    assert len(m.sources("2026-01-20")) == 2
    from chronicle.common import db

    with db(m.path) as c:
        assert c.execute("SELECT count(*) FROM notes").fetchone()[0] == 3
        assert (
            c.execute(
                "SELECT valid_from FROM notes WHERE source_id='old' AND claim_key='place'"
            )
            .fetchone()[0]
            .startswith("2026-01-01")
        )


def test_common_deletion_and_namespace_guard(tmp_path):
    path = tmp_path / "m.sqlite"
    m = Memory(path, "a")
    m.ingest([{"id": "s", "observed_at": "2026-01-01", "text": "秘密"}])
    m.delete("s")
    other = Memory(path, "b")
    other.ingest([{"id": "t", "observed_at": "2026-01-01", "text": "另一空间"}])
    assert not m.sources(None)
    assert len(other.sources(None)) == 1


def test_reingestion_tombstone_and_timezone(tmp_path):
    from chronicle.memory import instant

    assert instant("2026-10-01T08:30:00+08:00") == "2026-10-01T00:30:00"
    m = Memory(tmp_path / "memory.sqlite", "a")
    s = {"id": "old", "observed_at": "2026-10-01", "text": "地点A"}
    m.ingest([s])
    m.ingest([dict(s, deleted=True)])
    assert not m.sources(None)


def test_batch_derived_note_does_not_backdate_knowledge(tmp_path):
    class ExtractorFixture:
        def json(self, *args, **kwargs):
            return {
                "notes": [
                    {
                        "source_id": "old",
                        "fact": "地点B",
                        "quote": "地点",
                        "claim_key": "place",
                    }
                ]
            }, {"origin": "offline_fixture"}

    m = Memory(tmp_path / "memory.sqlite", "a")
    m.ingest(
        [
            {"id": "old", "observed_at": "2026-10-01", "text": "地点A"},
            {"id": "new", "observed_at": "2026-10-15", "text": "后来改成地点B"},
        ]
    )
    m.extract(ExtractorFixture())
    from chronicle.common import db

    with db(m.path) as c:
        n = c.execute("SELECT * FROM notes").fetchone()
        assert n["derived_known_at"] == "2026-10-15T00:00:00"
        assert set(__import__("json").loads(n["dependencies"])) == {"old", "new"}
