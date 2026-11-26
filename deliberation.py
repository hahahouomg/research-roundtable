"""Evidence raised by the reviewers and its status in the latest round."""
import hashlib
import json
import re

from providers import MODEL_SEATS


def review_prompt(base, proposals, sid, agent, focus):
    ordered = sorted(proposals, key=lambda seat: hashlib.sha256(f"{sid}/{seat}".encode()).digest())
    labels = {seat: chr(ord("A") + index) for index, seat in enumerate(ordered)}
    material = "\n\n".join(f"方案 {labels[seat]}\n{proposals[seat]}" for seat in ordered)
    return (
        f"{base}\n所有席位看到相同约束和完整候选。你的方案编号为 {labels[agent]}，重点审查{focus}，"
        "可以指出跨方案的问题。按编号引用对方的主张，不推断提案者身份。"
        "每项异议写一条能改变结论的检查，只有实质影响验收时标为阻塞。"
        "仅当存在证据缺口时补用工具。说明来源定位、观测、推断或未验证假设，避免把引用写成亲测。"
        '输出一个 JSON 对象，summary 为总体判断，items 为数组（无实质发现可为空）。每条包含 '
        '{"claim":"具体主张或异议","kind":"observation|reference|inference|untested",'
        '"source":"来源、命令及结果定位，可留空","blocking":true,"check":"可复现检查及判定标准，可留空"}。\n\n'
        + material
    )


def review_items(agent, reply):
    raw = reply.strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.partition("\n")[2][:-3]
    try:
        review = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(review, dict) or not isinstance(review.get("items"), list):
        return None
    items = []
    for index, item in enumerate(review["items"], 1):
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str) or not item["claim"].strip():
            continue
        fields = {key: item[key].strip() if isinstance(item.get(key), str) else "" for key in ("claim", "kind", "source", "check")}
        if fields["kind"] not in ("observation", "reference", "inference", "untested"):
            fields["kind"] = "untested"
        items.append(dict(fields, id=f"E{list(MODEL_SEATS).index(agent) + 1}.{index}", agent=agent,
                          blocking=item.get("blocking") is True and bool(fields["check"])))
    if review["items"] and not items:
        return None
    return items


def review_state(calls, seats):
    reviews, candidate, ballots = {}, None, {}
    for call in calls:
        if call["ended"] is None or call["error"] is not None or not call["reply"]:
            continue
        agent, stage = call["agent"], call["stage"]
        if stage == "交叉评议" and agent in MODEL_SEATS:
            reviews[agent] = call["reply"]
        version = re.fullmatch(r"(候选方案|表决) v(\d+)", stage)
        if version:
            try:
                data = json.loads(call["reply"])
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            number = int(version[2])
            if version[1] == "候选方案" and isinstance(data.get("plan"), str) and data["plan"].strip():
                if candidate is None or number >= candidate[0]:
                    candidate = (number, data)
            if version[1] == "表决" and data.get("vote") in ("accept", "object"):
                if isinstance(data.get("reason"), str) and data["reason"].strip():
                    ballots.setdefault(number, {})[agent] = data["vote"]
    if not reviews:
        return None
    items, original = [], []
    for agent, text in reviews.items():
        parsed = review_items(agent, text)
        if parsed is None:
            original.append(agent)
        else:
            items.extend(parsed)
    versions = candidate[1].get("dispositions", []) if candidate else []
    dispositions = {}
    if isinstance(versions, list):
        for response in versions:
            if isinstance(response, dict) and isinstance(response.get("id"), str):
                if isinstance(response.get("response"), str) and response["response"].strip():
                    dispositions[response["id"]] = response["response"].strip()
    for item in items:
        if item["id"] in dispositions:
            item["response"] = dispositions[item["id"]]
    votes = ballots.get(candidate[0], {}) if candidate else {}
    return dict(items=items, original=original, version=candidate[0] if candidate else None,
                votes={agent: votes[agent] for agent in seats if agent in votes}, seats=len(seats))
