from .audit import write
from .grants import TERMS_ORDER, Grants
from .policy import Policies


class Reviews:
    """复核轮次：登记轮次窗口，并回答“哪些反馈可用于哪一轮复核”。"""

    def __init__(self, connection):
        self.connection = connection
        self.grants = Grants(connection)
        self.policies = Policies(connection)

    def open_round(self, round_id, recipient, purpose, opens_at, closes_at, at, actor):
        if closes_at < opens_at:
            raise ValueError("轮次时间无效")
        if self.connection.execute("SELECT 1 FROM rounds WHERE id=?", (round_id,)).fetchone():
            raise ValueError("轮次编号已登记")
        with self.connection:
            self.connection.execute(
                "INSERT INTO rounds(id,recipient,purpose,opens_at,closes_at) VALUES(?,?,?,?,?)",
                (round_id, recipient, purpose, opens_at, closes_at),
            )
            write(self.connection, at, actor, "round.open", round_id,
                  {"recipient": recipient, "purpose": purpose, "closes_at": closes_at})

    def get_round(self, round_id):
        row = self.connection.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        if row is None:
            raise KeyError(round_id)
        return dict(row)

    def usable(self, round_id, at):
        """按时点列出该轮次可用的反馈：逐来源核对授权与规则，文本相同的不同来源记录各自独立判断。"""
        round_ = self.get_round(round_id)
        rows = self.connection.execute(
            "SELECT a.id AS asset_id, a.source_id, s.owner, s.jurisdiction, s.classification "
            "FROM assets a JOIN sources s ON s.id=a.source_id "
            "WHERE a.state='active' AND s.active=1 ORDER BY a.id"
        ).fetchall()
        usable = []
        for row in rows:
            decision, _ = self.policies.decision(row["jurisdiction"], row["classification"], round_["purpose"])
            if decision != "allow":
                continue
            grant = self.grants.active_grant(row["source_id"], round_["recipient"], round_["purpose"], at)
            if grant is None:
                continue
            forms = [form for form in ("raw", "redacted") if TERMS_ORDER[grant["terms"]] >= TERMS_ORDER[form]]
            redactions = [dict(item) for item in self.connection.execute(
                "SELECT id,version,method FROM redactions WHERE asset_id=? ORDER BY version",
                (row["asset_id"],)).fetchall()]
            usable.append({
                "asset_id": row["asset_id"],
                "source_id": row["source_id"],
                "owner": row["owner"],
                "grant_id": grant["id"],
                "terms": grant["terms"],
                "forms": forms,
                "redactions": redactions,
            })
        return usable
