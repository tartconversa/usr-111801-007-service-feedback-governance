from .audit import write

# 授权材料形态：raw 允许引用原文，redacted 仅允许引用脱敏材料。
# 形态只可按 raw -> redacted 收窄，撤销后不再可用。
TERMS_ORDER = {"redacted": 1, "raw": 2}


class Grants:
    def __init__(self, connection):
        self.connection = connection

    def issue(self, grant_id, source_id, recipient, purpose, valid_until, at, terms="raw"):
        if terms not in TERMS_ORDER:
            raise ValueError("授权形态无效")
        source = self.connection.execute("SELECT owner FROM sources WHERE id=?", (source_id,)).fetchone()
        if source is None:
            raise KeyError(source_id)
        with self.connection:
            self.connection.execute(
                "INSERT INTO grants(id,source_id,recipient,purpose,valid_until,terms) VALUES(?,?,?,?,?,?)",
                (grant_id, source_id, recipient, purpose, valid_until, terms),
            )
            self.connection.execute(
                "INSERT INTO grant_revisions(grant_id,revision,status,terms,valid_until,changed_at,actor) "
                "VALUES(?,?,?,?,?,?,?)",
                (grant_id, 1, "active", terms, valid_until, at, source["owner"]),
            )
            write(self.connection, at, source["owner"], "grant.issue", grant_id,
                  {"source": source_id, "recipient": recipient, "terms": terms})

    def narrow(self, grant_id, terms, at, actor, reason=""):
        if terms not in TERMS_ORDER:
            raise ValueError("授权形态无效")
        row = self._row(grant_id)
        if row is None:
            raise KeyError(grant_id)
        if row["status"] != "active":
            raise ValueError("授权已撤销，无法再收窄")
        if TERMS_ORDER[terms] >= TERMS_ORDER[row["terms"]]:
            raise ValueError("只能收窄授权形态")
        return self._append(row, "active", terms, at, actor, reason, "grant.narrow")

    def revoke(self, grant_id, at, actor, reason=""):
        row = self._row(grant_id)
        if row is None:
            raise KeyError(grant_id)
        if row["status"] != "active":
            raise ValueError("授权已撤销")
        return self._append(row, "revoked", row["terms"], at, actor, reason, "grant.revoke")

    def _append(self, row, status, terms, at, actor, reason, action):
        grant_id = row["id"]
        revision = self.connection.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM grant_revisions WHERE grant_id=?", (grant_id,)
        ).fetchone()[0]
        with self.connection:
            self.connection.execute(
                "UPDATE grants SET status=?,terms=? WHERE id=?", (status, terms, grant_id)
            )
            self.connection.execute(
                "INSERT INTO grant_revisions(grant_id,revision,status,terms,valid_until,changed_at,actor,reason) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (grant_id, revision, status, terms, row["valid_until"], at, actor, reason),
            )
            write(self.connection, at, actor, action, grant_id,
                  {"status": status, "terms": terms, "revision": revision, "reason": reason})
        return revision

    def _row(self, grant_id):
        return self.connection.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()

    def active_grant(self, source_id, recipient, purpose, at):
        row = self.connection.execute(
            "SELECT * FROM grants WHERE source_id=? AND recipient=? AND purpose=? "
            "AND status='active' AND valid_until>=? ORDER BY id LIMIT 1",
            (source_id, recipient, purpose, at),
        ).fetchone()
        return dict(row) if row else None

    def permits(self, source_id, recipient, purpose, at, form="raw"):
        grant = self.active_grant(source_id, recipient, purpose, at)
        if grant is None or TERMS_ORDER[grant["terms"]] < TERMS_ORDER[form]:
            return None
        return grant["id"]

    def current_revision(self, grant_id):
        return self.connection.execute(
            "SELECT COALESCE(MAX(revision),0) FROM grant_revisions WHERE grant_id=?", (grant_id,)
        ).fetchone()[0]

    def revision_of(self, grant_id, revision):
        row = self.connection.execute(
            "SELECT * FROM grant_revisions WHERE grant_id=? AND revision=?", (grant_id, revision)
        ).fetchone()
        return dict(row) if row else None

    def revisions(self, grant_id):
        rows = self.connection.execute(
            "SELECT * FROM grant_revisions WHERE grant_id=? ORDER BY revision", (grant_id,)
        ).fetchall()
        return [dict(row) for row in rows]
