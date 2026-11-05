"""Synthetic work histories. Evaluation labels are never sent to memory ingestion."""

from __future__ import annotations
import random


def build_custom():
    rng = random.Random(2026110102)
    histories = []
    for i in range(20):
        name = f"工作空间{i:02d}"
        project = f"青禾{i:02d}"
        owner = f"研究员{i + 20}"
        old_region, new_region = f"区域{i + 1}A", f"区域{i + 1}B"
        old_quota, new_quota = 30 + i, 65 + i
        budget, used = 200 + i * 3, 51 + i
        sources = []

        def add(n, date, text, deleted=False):
            sid = f"h{i:02d}-s{n}"
            sources.append(
                {"id": sid, "observed_at": date, "text": text, "deleted": deleted}
            )
            return sid

        code = add(
            "code", "2026-09-01", f"请记住：{project}的项目代号是HARBOR-{701 + i}。"
        )
        own = add(
            "owner", "2026-09-02", f"{project}的负责人是{owner}，不是其他空间的人。"
        )
        reg0 = add("region0", "2026-09-03", f"{project}从9月3日起部署在{old_region}。")
        q0 = add(
            "quota0", "2026-09-04", f"{project}9月4日起的每日测试配额为{old_quota}次。"
        )
        b = add("budget", "2026-09-05", f"{project}本阶段的预算为{budget}元。")
        u = add(
            "used", "2026-09-06", f"{project}本阶段已经使用{used}元，暂无其他费用。"
        )
        domain = add(
            "domain", "2026-09-07", f"{project}的服务域名为field-{i}.example.test。"
        )
        contact = add(
            "contact",
            "2026-09-08",
            f"{project}联系人电话为虚构号码000-{5000 + i}，之后请求删除。",
            True,
        )
        legacy = add(
            "legacy",
            "2026-09-09",
            f"{project}旧仓库为虚构地址legacy-{i}，这条资料已删除。",
            True,
        )
        reg1 = add(
            "region1",
            "2026-09-12",
            f"更正{project}部署地点：从9月12日起改到{new_region}，取代先前的{old_region}，9月12日以前不变。",
        )
        q1 = add(
            "quota1",
            "2026-09-15",
            f"更正{project}配额，从9月15日起每日{new_quota}次；此前仍为{old_quota}次。",
        )
        # Relevant-looking but non-authoritative chatter makes mere last-N packing
        # different from retrieving durable facts. This is synthetic stress data.
        for j in range(48):
            words = [
                rng.choice(
                    [
                        "研讨",
                        "演示",
                        "界面",
                        "天气",
                        "散步",
                        "草稿",
                        "约定",
                        "背景",
                        "记录",
                        "讨论",
                    ]
                )
                for _ in range(120)
            ]
            add(
                f"noise{j}",
                f"2026-10-{1 + j // 2:02d}",
                f"{name}第{j}条非正式闲聊，无新增项目决策：" + "，".join(words),
            )
        questions = []

        def ask(kind, index, question, expected, refs, *, as_of="2026-10-31"):
            questions.append(
                {
                    "id": f"h{i:02d}-{kind}-{index}",
                    "category": kind,
                    "question": question,
                    "answer": expected,
                    "answerable": expected is not None,
                    "required_sources": refs,
                    "known_at": "2026-10-31",
                    "as_of": as_of,
                }
            )

        ask("extract", 0, f"{project}的项目代号是什么？", f"HARBOR-{701 + i}", [code])
        ask("extract", 1, f"谁负责{project}？", owner, [own])
        ask("update", 0, f"{project}现在部署在哪个区域？", new_region, [reg1])
        ask("update", 1, f"{project}目前每日测试配额是多少次？", str(new_quota), [q1])
        ask(
            "temporal",
            0,
            f"9月10日，{project}部署在哪个区域？",
            old_region,
            [reg0],
            as_of="2026-09-10",
        )
        ask(
            "temporal",
            1,
            f"9月10日，{project}每日测试配额是多少次？",
            str(old_quota),
            [q0],
            as_of="2026-09-10",
        )
        for q in questions:
            if q["category"] == "temporal":
                q["acceptable_source_sets"] = [
                    q["required_sources"],
                    [reg1 if q["id"].endswith("-0") else q1],
                ]
        ask("multi", 0, f"{project}本阶段还剩多少元预算？", str(budget - used), [b, u])
        ask(
            "multi",
            1,
            f"请同时给出{project}的负责人和服务域名。",
            [owner, f"field-{i}.example.test"],
            [own, domain],
        )
        ask("unknown", 0, f"{project}负责人已经确定的入职日期是哪天？", None, [])
        ask("unknown", 1, f"{project}已经决定购买哪一种显卡？", None, [])
        ask("deleted", 0, f"{project}联系人的电话号码是什么？", None, [])
        ask("deleted", 1, f"{project}旧仓库的地址是什么？", None, [])
        histories.append(
            {
                "id": f"history-{i:02d}",
                "split": "dev" if i < 8 else "test",
                "language": "zh",
                "sources": sources,
                "questions": questions,
                "origin": "assistant_authored_synthetic_work_history",
            }
        )
    return histories


def public_cases(path):
    import json

    data = json.loads(path.read_text())
    for item in data:
        sessions = []
        counts = {}
        for sid in item["haystack_session_ids"]:
            counts[sid] = counts.get(sid, 0) + 1
        for index, (sid, date, turns) in enumerate(
            zip(
                item["haystack_session_ids"],
                item["haystack_dates"],
                item["haystack_sessions"],
            )
        ):
            # has_answer is deliberately excluded. Only role and content survive.
            text = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
            unique = sid if counts[sid] == 1 else f"{sid}::occurrence-{index}"
            sessions.append(
                {
                    "id": unique,
                    "origin_session_id": sid,
                    "observed_at": date,
                    "text": text,
                }
            )
        yield {
            "id": item["question_id"],
            "language": "en",
            "sources": sessions,
            "question": item["question"],
            "date": item["question_date"],
            "private": {
                "answer": item["answer"],
                "type": item["question_type"],
                "evidence_sessions": item["answer_session_ids"],
                "answerable": "_abs" not in item["question_id"],
            },
        }
