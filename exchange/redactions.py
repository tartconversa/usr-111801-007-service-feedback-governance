import hashlib
import json

from .audit import write


class Redactions:
    """反馈原件的脱敏版本。每份脱敏材料只对应一份原件，记录遮蔽方式与版本。"""

    def __init__(self, connection):
        self.connection = connection

    def create(self, redaction_id, asset_id, masked_payload, method, at, actor):
        asset = self.connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        if asset["state"] != "active":
            raise ValueError("反馈记录不可用")
        if not method:
            raise ValueError("身份遮蔽方式缺失")
        if self.connection.execute("SELECT 1 FROM redactions WHERE id=?", (redaction_id,)).fetchone():
            raise ValueError("脱敏版本编号已登记")
        allowed = {row[0] for row in self.connection.execute(
            "SELECT name FROM fields WHERE source_id=?", (asset["source_id"],))}
        if not isinstance(masked_payload, dict) or not masked_payload or set(masked_payload) - allowed:
            raise ValueError("脱敏材料字段不符合来源目录")
        canonical = json.dumps(masked_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        version = self.connection.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM redactions WHERE asset_id=?", (asset_id,)
        ).fetchone()[0]
        with self.connection:
            self.connection.execute(
                "INSERT INTO redactions(id,asset_id,version,method,masked_payload,digest,created_at,created_by) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (redaction_id, asset_id, version, method, canonical, digest, at, actor),
            )
            write(self.connection, at, actor, "redaction.create", redaction_id,
                  {"asset": asset_id, "version": version, "method": method, "digest": digest})
        return version

    def get(self, redaction_id):
        row = self.connection.execute("SELECT * FROM redactions WHERE id=?", (redaction_id,)).fetchone()
        if row is None:
            raise KeyError(redaction_id)
        return dict(row)

    def of_asset(self, asset_id):
        rows = self.connection.execute(
            "SELECT * FROM redactions WHERE asset_id=? ORDER BY version", (asset_id,)
        ).fetchall()
        return [dict(row) for row in rows]
