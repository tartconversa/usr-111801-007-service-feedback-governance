import argparse
import json
from .service import Exchange


def show(label, value):
    print(label, json.dumps(value, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description="景区资料本地协作演练")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    service = Exchange(args.database)
    try:
        service.catalog.register("source", "资料室", "甲地", "review",
                                 [("finding", "服务观察", "text", False)], "2026-11-17")
        service.catalog.ingest("item-1", "source", {"finding": "指引可见"}, "2026-11-17")
        service.grants.issue("g-1", "source", "复核组", "质量复核", "2026-12-31", "2026-11-17")
        service.policies.set("甲地", "review", "质量复核", "allow", "2026-11-17", "资料室")
        revision = service.products.assemble("dossier", "复核资料", ["item-1"], "2026-11-17", "资料室")
        receipt = service.delivery.send("d-1", "dossier", revision, "复核组", "质量复核", "2026-11-17")
        show("交付回执:", receipt)

        # 游客服务反馈治理演练：同一反馈经两个平台转送，授权各自独立
        fields = [("text", "反馈原文", "text", True), ("score", "评分", "integer", False)]
        service.catalog.register("platform-a", "平台甲", "甲地", "feedback", fields, "2026-11-17")
        service.catalog.register("platform-b", "平台乙", "甲地", "feedback", fields, "2026-11-17")
        service.catalog.ingest("fb-a", "platform-a", {"text": "索道排队两小时", "score": 2}, "2026-11-17")
        service.catalog.ingest("fb-b", "platform-b", {"text": "索道排队两小时", "score": 2}, "2026-11-17")
        service.policies.set("甲地", "feedback", "质量复核", "allow", "2026-11-17", "资料室")
        service.grants.issue("g-a", "platform-a", "复核组", "质量复核", "2026-12-31", "2026-11-17")
        service.reviews.open_round("round-1", "复核组", "质量复核", "2026-11-01", "2026-12-31",
                                   "2026-11-17", "资料室")
        service.redactions.create("red-a-1", "fb-a", {"score": 2}, "隐去昵称与订单号", "2026-11-17", "资料室")
        show("本轮可用反馈:", service.reviews.usable("round-1", "2026-11-18"))
        service.citations.add("cite-1", "round-1", "fb-a", "索道服务评级：待改进", "redacted",
                              "2026-11-18", "复核组", redaction_id="red-a-1")
        service.grants.narrow("g-a", "redacted", "2026-11-19", "平台甲", "游客要求隐去身份")
        try:
            service.citations.add("cite-2", "round-1", "fb-a", "补充摘要", "raw", "2026-11-20", "复核组")
        except PermissionError as exc:
            show("收窄后引用原文被拒:", str(exc))
        show("历史引用解释:", service.citations.explain("cite-1"))
    finally:
        service.close()


if __name__ == "__main__":
    main()
