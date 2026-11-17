from .audit import write
from .grants import TERMS_ORDER, Grants
from .policy import Policies


class Citations:
    """评级引用：把已发布结论与证据版本、授权版本、规则版本绑定，登记后不可更改。"""

    def __init__(self, connection):
        self.connection = connection
        self.grants = Grants(connection)
        self.policies = Policies(connection)

    def add(self, citation_id, round_id, asset_id, conclusion, quote_form, at, actor, redaction_id=None):
        if quote_form not in TERMS_ORDER:
            raise ValueError("引用形态无效")
        if not conclusion:
            raise ValueError("评级结论缺失")
        if self.connection.execute("SELECT 1 FROM citations WHERE id=?", (citation_id,)).fetchone():
            raise ValueError("引用编号已登记")
        round_ = self.connection.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        if round_ is None:
            raise KeyError(round_id)
        if not (round_["opens_at"] <= at <= round_["closes_at"]):
            raise ValueError("复核轮次未开放")
        asset = self.connection.execute(
            "SELECT a.*,s.active AS source_active,s.jurisdiction,s.classification "
            "FROM assets a JOIN sources s ON s.id=a.source_id WHERE a.id=?", (asset_id,)
        ).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        if asset["state"] != "active" or not asset["source_active"]:
            raise ValueError("反馈记录不可用")
        grant = self.grants.active_grant(asset["source_id"], round_["recipient"], round_["purpose"], at)
        if grant is None:
            raise PermissionError("缺少覆盖该轮次的有效授权")
        if TERMS_ORDER[grant["terms"]] < TERMS_ORDER[quote_form]:
            raise PermissionError("授权已收窄，摘要不得引用原文")
        if quote_form == "redacted":
            if redaction_id is None:
                raise ValueError("引用脱敏材料缺失")
            redaction = self.connection.execute(
                "SELECT * FROM redactions WHERE id=?", (redaction_id,)).fetchone()
            if redaction is None:
                raise KeyError(redaction_id)
            if redaction["asset_id"] != asset_id:
                raise ValueError("脱敏材料与反馈不对应")
        elif redaction_id is not None:
            raise ValueError("原文引用不应关联脱敏材料")
        decision, policy_revision = self.policies.decision(
            asset["jurisdiction"], asset["classification"], round_["purpose"])
        if decision != "allow":
            raise PermissionError("现行规则不允许该用途")
        grant_revision = self.grants.current_revision(grant["id"])
        with self.connection:
            self.connection.execute(
                "INSERT INTO citations(id,round_id,asset_id,redaction_id,grant_id,grant_revision,"
                "policy_revision,quote_form,conclusion,created_at,actor) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (citation_id, round_id, asset_id, redaction_id, grant["id"], grant_revision,
                 policy_revision, quote_form, conclusion, at, actor),
            )
            write(self.connection, at, actor, "citation.add", citation_id,
                  {"round": round_id, "asset": asset_id, "redaction": redaction_id,
                   "grant": grant["id"], "grant_revision": grant_revision, "quote_form": quote_form})
        return dict(self.connection.execute("SELECT * FROM citations WHERE id=?", (citation_id,)).fetchone())

    def of_round(self, round_id):
        rows = self.connection.execute(
            "SELECT * FROM citations WHERE round_id=? ORDER BY created_at,id", (round_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def explain(self, citation_id):
        """解释历史结论当时使用的证据版本与处理依据；授权此后收窄或撤销不影响该快照。"""
        row = self.connection.execute("SELECT * FROM citations WHERE id=?", (citation_id,)).fetchone()
        if row is None:
            raise KeyError(citation_id)
        citation = dict(row)
        round_ = self.connection.execute("SELECT * FROM rounds WHERE id=?", (citation["round_id"],)).fetchone()
        asset = self.connection.execute(
            "SELECT a.id,a.source_id,a.digest,a.received_at,s.jurisdiction,s.classification "
            "FROM assets a JOIN sources s ON s.id=a.source_id WHERE a.id=?", (citation["asset_id"],)
        ).fetchone()
        redaction = None
        if citation["redaction_id"] is not None:
            redaction = dict(self.connection.execute(
                "SELECT id,asset_id,version,method,digest,created_at,created_by FROM redactions WHERE id=?",
                (citation["redaction_id"],)).fetchone())
        grant_revision = self.grants.revision_of(citation["grant_id"], citation["grant_revision"])
        grant_now = self.connection.execute(
            "SELECT status,terms,valid_until FROM grants WHERE id=?", (citation["grant_id"],)).fetchone()
        return {
            "citation": citation,
            "round": dict(round_),
            "asset": dict(asset),
            "redaction": redaction,
            "grant_revision": grant_revision,
            "grant_current": dict(grant_now) if grant_now else None,
            "policy": {
                "revision": citation["policy_revision"],
                "decision": self.policies.revision_decision(
                    asset["jurisdiction"], asset["classification"],
                    round_["purpose"], citation["policy_revision"]),
            },
        }
