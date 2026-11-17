import tempfile
import unittest
from pathlib import Path

from exchange import Exchange


class ExchangeFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "exchange.db")
        self.service.catalog.register("flow", "机构甲", "甲地", "restricted", [("count", "通行计数", "integer", False)], "2026-11-01")
        self.service.catalog.ingest("item-1", "flow", {"count": 8}, "2026-11-02")
        self.service.grants.issue("g-1", "flow", "机构乙", "运行协调", "2026-12-31", "2026-11-03")
        self.service.policies.set("甲地", "restricted", "运行协调", "allow", "2026-11-03", "机构甲")
        self.revision = self.service.products.assemble("report", "通行观察", ["item-1"], "2026-11-04", "机构甲")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_delivery_keeps_revision_and_request_identity(self):
        desk = self.service.delivery
        receipt = desk.send("d-1", "report", self.revision, "机构乙", "运行协调", "2026-11-05")
        self.assertEqual(receipt["product_revision"], self.revision)
        self.assertEqual(receipt, desk.send("d-1", "report", self.revision, "机构乙", "运行协调", "2026-11-05"))
        with self.assertRaises(ValueError):
            desk.send("d-1", "report", self.revision, "其他机构", "运行协调", "2026-11-05")

    def test_grant_and_policy_gate_delivery(self):
        with self.assertRaises(PermissionError):
            self.service.delivery.send("d-2", "report", self.revision, "陌生机构", "运行协调", "2026-11-05")
        self.service.policies.set("甲地", "restricted", "运行协调", "deny", "2026-11-06", "机构甲")
        with self.assertRaises(PermissionError):
            self.service.delivery.send("d-3", "report", self.revision, "机构乙", "运行协调", "2026-11-07")
        self.assertTrue(self.service.history("report"))

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            self.service.catalog.ingest("item-2", "flow", {"unknown": 9}, "2026-11-03")


class FeedbackGovernanceTest(unittest.TestCase):
    """游客服务反馈：来源授权、脱敏材料与评级引用的关联治理。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Exchange(Path(self.temp.name) / "exchange.db")
        fields = [("text", "反馈原文", "text", True), ("score", "评分", "integer", False)]
        # 同一反馈经两个平台转送，登记为两个来源下的两份原件
        self.service.catalog.register("platform-a", "平台甲", "甲地", "feedback", fields, "2026-11-01")
        self.service.catalog.register("platform-b", "平台乙", "甲地", "feedback", fields, "2026-11-01")
        self.service.catalog.ingest("fb-a", "platform-a", {"text": "索道排队两小时", "score": 2}, "2026-11-02")
        self.service.catalog.ingest("fb-b", "platform-b", {"text": "索道排队两小时", "score": 2}, "2026-11-02")
        self.service.policies.set("甲地", "feedback", "质量复核", "allow", "2026-11-01", "资料室")
        self.service.grants.issue("g-a", "platform-a", "复核组", "质量复核", "2026-12-31", "2026-11-02")
        self.service.reviews.open_round("round-1", "复核组", "质量复核", "2026-11-01", "2026-12-31",
                                        "2026-11-01", "资料室")
        self.service.redactions.create("red-a-1", "fb-a", {"score": 2}, "隐去昵称与订单号",
                                       "2026-11-03", "资料室")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def usable_assets(self, at="2026-11-04"):
        return {item["asset_id"]: item for item in self.service.reviews.usable("round-1", at)}

    def test_usable_listed_per_round_and_per_source(self):
        usable = self.usable_assets()
        # 平台甲有授权：可用，且条款允许原文与脱敏两种形态
        self.assertEqual(usable["fb-a"]["forms"], ["raw", "redacted"])
        self.assertEqual(usable["fb-a"]["grant_id"], "g-a")
        self.assertEqual([r["id"] for r in usable["fb-a"]["redactions"]], ["red-a-1"])
        # 平台乙转送同一文本但无授权：不因文本相似而并入平台甲的授权
        self.assertNotIn("fb-b", usable)
        self.assertEqual(self.service.catalog.get("fb-a")["digest"],
                         self.service.catalog.get("fb-b")["digest"])

    def test_citation_links_redaction_grant_and_policy_versions(self):
        citation = self.service.citations.add(
            "cite-1", "round-1", "fb-a", "索道服务评级：待改进", "redacted",
            "2026-11-04", "复核组", redaction_id="red-a-1")
        self.assertEqual(citation["grant_id"], "g-a")
        self.assertEqual(citation["grant_revision"], 1)
        self.assertEqual(citation["policy_revision"], 1)
        explanation = self.service.citations.explain("cite-1")
        self.assertEqual(explanation["redaction"]["version"], 1)
        self.assertEqual(explanation["redaction"]["method"], "隐去昵称与订单号")
        self.assertEqual(explanation["grant_revision"]["terms"], "raw")
        self.assertEqual(explanation["policy"]["decision"], "allow")

    def test_narrowed_grant_blocks_future_raw_quotes(self):
        self.service.citations.add("cite-raw", "round-1", "fb-a", "现场摘要引用原文", "raw",
                                   "2026-11-04", "复核组")
        self.service.grants.narrow("g-a", "redacted", "2026-11-10", "平台甲", "游客要求隐去身份")
        # 收窄后：未来摘要不得再引用原文，但仍可引用脱敏材料
        with self.assertRaises(PermissionError):
            self.service.citations.add("cite-raw-2", "round-1", "fb-a", "继续引用原文", "raw",
                                       "2026-11-11", "复核组")
        followup = self.service.citations.add("cite-red", "round-1", "fb-a", "改用脱敏材料", "redacted",
                                              "2026-11-11", "复核组", redaction_id="red-a-1")
        self.assertEqual(followup["grant_revision"], 2)
        self.assertEqual(self.usable_assets("2026-11-11")["fb-a"]["forms"], ["redacted"])
        # 历史结论仍能解释当时依据：授权版本 1 允许原文
        explanation = self.service.citations.explain("cite-raw")
        self.assertEqual(explanation["grant_revision"]["terms"], "raw")
        self.assertEqual(explanation["grant_revision"]["status"], "active")
        self.assertEqual(explanation["grant_current"]["terms"], "redacted")

    def test_revoked_grant_blocks_new_citations_but_keeps_history(self):
        self.service.citations.add("cite-1", "round-1", "fb-a", "评级结论", "redacted",
                                   "2026-11-04", "复核组", redaction_id="red-a-1")
        self.service.grants.revoke("g-a", "2026-11-10", "平台甲", "游客撤回授权")
        with self.assertRaises(PermissionError):
            self.service.citations.add("cite-2", "round-1", "fb-a", "新摘要", "redacted",
                                       "2026-11-11", "复核组", redaction_id="red-a-1")
        self.assertNotIn("fb-a", self.usable_assets("2026-11-11"))
        explanation = self.service.citations.explain("cite-1")
        self.assertEqual(explanation["grant_revision"]["status"], "active")
        self.assertEqual(explanation["grant_current"]["status"], "revoked")
        revisions = self.service.grants.revisions("g-a")
        self.assertEqual([(r["revision"], r["status"]) for r in revisions],
                         [(1, "active"), (2, "revoked")])

    def test_narrow_and_revoke_validate_state(self):
        with self.assertRaises(ValueError):
            self.service.grants.narrow("g-a", "raw", "2026-11-10", "平台甲")
        self.service.grants.revoke("g-a", "2026-11-10", "平台甲")
        with self.assertRaises(ValueError):
            self.service.grants.narrow("g-a", "redacted", "2026-11-11", "平台甲")
        with self.assertRaises(ValueError):
            self.service.grants.revoke("g-a", "2026-11-12", "平台甲")

    def test_forwarded_feedback_authorizations_stay_separate(self):
        # 平台乙无授权：其转送件不能引用，即使文本与平台甲一致
        with self.assertRaises(PermissionError):
            self.service.citations.add("cite-b", "round-1", "fb-b", "评级结论", "redacted",
                                       "2026-11-04", "复核组", redaction_id="red-a-1")
        # 平台乙有自己的授权后：也不能借用平台甲原件的脱敏材料
        self.service.grants.issue("g-b", "platform-b", "复核组", "质量复核", "2026-12-31", "2026-11-03")
        with self.assertRaises(ValueError):
            self.service.citations.add("cite-b", "round-1", "fb-b", "评级结论", "redacted",
                                       "2026-11-04", "复核组", redaction_id="red-a-1")
        self.service.redactions.create("red-b-1", "fb-b", {"score": 2}, "平台乙遮蔽规则",
                                       "2026-11-04", "资料室")
        citation = self.service.citations.add("cite-b", "round-1", "fb-b", "评级结论", "redacted",
                                              "2026-11-05", "复核组", redaction_id="red-b-1")
        self.assertEqual(citation["grant_id"], "g-b")

    def test_withdrawn_feedback_unusable_but_history_explainable(self):
        self.service.citations.add("cite-1", "round-1", "fb-a", "评级结论", "redacted",
                                   "2026-11-04", "复核组", redaction_id="red-a-1")
        self.service.catalog.withdraw("fb-a", "2026-11-10", "平台甲", "游客删除请求")
        self.assertNotIn("fb-a", self.usable_assets("2026-11-11"))
        with self.assertRaises(ValueError):
            self.service.citations.add("cite-2", "round-1", "fb-a", "新摘要", "redacted",
                                       "2026-11-11", "复核组", redaction_id="red-a-1")
        with self.assertRaises(ValueError):
            self.service.redactions.create("red-a-2", "fb-a", {"score": 1}, "再次脱敏",
                                           "2026-11-11", "资料室")
        explanation = self.service.citations.explain("cite-1")
        self.assertEqual(explanation["asset"]["digest"], self.service.catalog.get("fb-a")["digest"])
        self.assertEqual(explanation["redaction"]["id"], "red-a-1")

    def test_policy_flip_keeps_historical_basis(self):
        self.service.citations.add("cite-1", "round-1", "fb-a", "评级结论", "redacted",
                                   "2026-11-04", "复核组", redaction_id="red-a-1")
        self.service.policies.set("甲地", "feedback", "质量复核", "deny", "2026-11-10", "资料室")
        with self.assertRaises(PermissionError):
            self.service.citations.add("cite-2", "round-1", "fb-a", "新摘要", "redacted",
                                       "2026-11-11", "复核组", redaction_id="red-a-1")
        explanation = self.service.citations.explain("cite-1")
        self.assertEqual(explanation["policy"], {"revision": 1, "decision": "allow"})

    def test_citation_validates_round_and_material(self):
        with self.assertRaises(ValueError):
            self.service.citations.add("cite-x", "round-1", "fb-a", "过早结论", "raw",
                                       "2026-10-15", "复核组")
        with self.assertRaises(ValueError):
            self.service.citations.add("cite-x", "round-1", "fb-a", "缺脱敏材料", "redacted",
                                       "2026-11-04", "复核组")
        with self.assertRaises(ValueError):
            self.service.citations.add("cite-x", "round-1", "fb-a", "形态混淆", "raw",
                                       "2026-11-04", "复核组", redaction_id="red-a-1")
        with self.assertRaises(ValueError):
            self.service.redactions.create("red-bad", "fb-a", {"unknown": 1}, "方式",
                                           "2026-11-04", "资料室")


if __name__ == "__main__":
    unittest.main()
