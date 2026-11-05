"""Store source-linked user fact revisions; retain temporary and uncertain evidence."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Revision:
    sequence: int
    source: str
    owner: str
    attribute: str
    value: str
    kind: str


@dataclass
class Timeline:
    entries: list[Revision] = field(default_factory=list)
    originals: dict[int, str] = field(default_factory=dict)

    def append(self, sequence, text, facts):
        if sequence in self.originals:
            if self.originals[sequence] != text:
                raise ValueError("Conflicting session identity")
            return
        self.originals[sequence] = text
        for fact in facts:
            quote = fact.get("quote")
            if not isinstance(quote, str) or not quote.strip() or quote not in text:
                continue
            kind = fact.get("kind")
            fields = [fact.get(k) for k in ("owner", "attribute", "value")]
            if kind in {"standing", "temporary", "uncertain"} and all(
                isinstance(v, str) and v.strip() for v in fields
            ):
                self.entries.append(Revision(sequence, quote, *fields, kind))

    def evidence(self, owner, attribute, *, as_of=None, include_temporary=False):
        items = [
            r
            for r in self.entries
            if (r.owner, r.attribute) == (owner, attribute)
            and (as_of is None or r.sequence <= as_of)
        ]
        standing = [r for r in items if r.kind == "standing"]
        current = max(standing, key=lambda r: r.sequence, default=None)
        evidence = [current] if current else []
        evidence.extend(
            r
            for r in items
            if r.kind == "uncertain" or (include_temporary and r.kind == "temporary")
        )
        return [f"Session {r.sequence}: {r.source}" for r in evidence]
