"""Real reader witnesses for knowledge-time, deletion and namespace boundaries."""

from .common import ROOT, freeze, write_json, rate, digest
from .memory import Memory, answer
from .memory_eval import scalar_correct
from .model import Model


def run(out):
    sources = [
        {
            "id": "old",
            "observed_at": "2026-10-01",
            "text": "2026年10月1日起，赤杉实验的预算记为900元。",
        },
        {
            "id": "correction",
            "observed_at": "2026-10-20",
            "text": "更正：10月1日起赤杉实验的预算应为1100元，旧记录900元有误。更正凭证编号COR-773。",
        },
        {
            "id": "future",
            "observed_at": "2026-10-30",
            "text": "2026年10月30日起赤杉实验预算调整为1200元；在此之前按更正后的1100元执行。",
        },
    ]
    cases = [
        {
            "id": "not_yet_known",
            "question": "赤杉实验在2026年10月5日有效的预算金额是多少？",
            "known_at": "2026-10-10",
            "as_of": "2026-10-05",
            "answer": "900",
            "forbidden": ["correction", "future", "foreign"],
        },
        {
            "id": "retroactive_correction_known",
            "question": "赤杉实验在2026年10月5日有效的预算金额是多少？",
            "known_at": "2026-10-25",
            "as_of": "2026-10-05",
            "answer": "1100",
            "forbidden": ["future", "foreign"],
        },
        {
            "id": "current_change",
            "question": "赤杉实验在2026年10月31日有效的预算金额是多少？",
            "known_at": "2026-10-31",
            "as_of": "2026-10-31",
            "answer": "1200",
            "forbidden": ["foreign"],
        },
        {
            "id": "other_scope",
            "question": "另一团队玄鲸实验的保密预算金额是多少？",
            "known_at": "2026-10-31",
            "as_of": "2026-10-31",
            "answer": None,
            "forbidden": ["foreign"],
        },
        {
            "id": "deleted_quote",
            "delete": "correction",
            "question": "赤杉实验的更正凭证编号是什么？",
            "known_at": "2026-10-31",
            "as_of": "2026-10-31",
            "answer": None,
            "forbidden": ["correction", "foreign"],
        },
        {
            "id": "older_view_after_deletion",
            "question": "赤杉实验在2026年10月5日有效的预算金额是多少？",
            "known_at": "2026-10-10",
            "as_of": "2026-10-05",
            "answer": "900",
            "forbidden": ["correction", "future", "foreign"],
        },
    ]
    freeze(
        out,
        {
            "sources": sources,
            "cases": cases,
            "arms": ["M0", "M1", "M2"],
            "purpose": "Six controlled witness queries, not primary QA corpus or field-reliability sample",
            "source": {
                n: digest((ROOT / "src/chronicle" / n).read_bytes())
                for n in ("memory.py", "memory_witnesses.py", "model.py")
            },
        },
    )
    if (out / "summary.json").exists():
        return
    m = Memory(out / "memory.sqlite", "team-A")
    m.ingest(sources)
    foreign = Memory(out / "memory.sqlite", "team-B")
    foreign.ingest(
        [
            {
                "id": "foreign",
                "observed_at": "2026-10-01",
                "text": "玄鲸实验的保密预算为77889元。",
            }
        ]
    )
    model = Model()
    extracted = m.extract(model)
    write_json(out / "ingestion.json", extracted)
    rows = []
    for c in cases:
        if c.get("delete"):
            m.delete(c["delete"])
        for arm in ("M0", "M1", "M2"):
            ev, info = m.context(c["question"], arm, c["known_at"], c["as_of"], "zh")
            reply, meta, _ = answer(
                model,
                c["question"],
                ev,
                label=f"P2:witness:{c['id']}:{arm}",
                known_at=c["known_at"],
                as_of=c["as_of"],
            )
            value_ok = (
                reply.get("abstain") is True
                if c["answer"] is None
                else not reply.get("abstain")
                and scalar_correct(reply.get("answer", ""), c["answer"])
            )
            eligible = not ({e["source_id"] for e in ev} & set(c["forbidden"]))
            rows.append(
                {
                    "case": c["id"],
                    "arm": arm,
                    "answer_correct": bool(value_ok),
                    "eligibility_pass": eligible,
                    "success": bool(value_ok and eligible),
                    "answer": reply,
                    "evidence": ev,
                    "usage": meta["usage"],
                }
            )
    write_json(
        out / "summary.json",
        {
            "all": rate(sum(r["success"] for r in rows), len(rows)),
            "eligibility": rate(sum(r["eligibility_pass"] for r in rows), len(rows)),
            "rows": rows,
            "limit": "Logical retrieval/dependent-note invalidation, not physical erasure of stored DB/evidence; synthetic controlled facts",
        },
    )


if __name__ == "__main__":
    run(ROOT / "evidence/P2/time_deletion_scope_v1")
