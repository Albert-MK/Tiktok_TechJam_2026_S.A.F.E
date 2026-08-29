"""Agent 单元测试。

重点不是「跑得通」，而是锁住整套架构赖以成立的几条不变量：

1. `user_model` 必须与评测器的生成逻辑逐字节一致——它是所有推理的基石，
   一旦漂移，逆向推理就会系统性地指向错误的商品。
2. 交卷策略必须遵守记分规则推导出的最优停止规则（宁可少交、不要凑数）。
3. 措辞被改写时不能崩，也不能返回空候选。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluator import local_evaluator as ev
from starter import user_model as um
from starter.agent import Agent
from starter.catalog_index import CatalogIndex
from starter.policy import endgame_plan, turn_utility

SAMPLE_PRODUCTS = [
    {
        "parent_asin": "B001", "title": "Merino Wool Hiking Socks",
        "features": ["Cushioned footbed", "Seamless toe"],
        "details": {"Department": "Mens", "Closure": "Pull On"},
        "description": ["Warm socks for cold weather hiking."],
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Socks"],
        "store": "TrailCo", "price": 18.5, "average_rating": 4.6, "rating_number": 9000,
    },
    {
        "parent_asin": "B002", "title": "Cotton Crew Socks 6-Pack",
        "features": ["Breathable cotton blend", "Reinforced heel"],
        "details": {"Department": "Mens", "Closure": "Pull On"},
        "description": ["Everyday crew socks."],
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Socks"],
        "store": "BasicWear", "price": 12.0, "average_rating": 4.3, "rating_number": 250,
    },
    {
        "parent_asin": "B003", "title": "Leather Chelsea Boot",
        "features": ["Full grain leather upper", "Rubber sole"],
        "details": {"Department": "Womens"},
        "description": ["Classic ankle boot."],
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Boots"],
        "store": "Stride", "price": 120.0, "average_rating": 4.1, "rating_number": 40,
    },
]


def write_catalog(products) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for product in products:
        handle.write(json.dumps(product) + "\n")
    handle.close()
    return handle.name


class UserModelFidelityTest(unittest.TestCase):
    """逆向推理的前提：我们复刻的生成过程必须和评测器完全一致。"""

    def test_intent_card_matches_evaluator(self):
        for product in SAMPLE_PRODUCTS:
            expected = ev.intent_card(product)
            hard, soft = um.intent_card(product)
            self.assertEqual(hard, expected["hard_constraints"], product["parent_asin"])
            self.assertEqual(soft, expected["soft_preferences"], product["parent_asin"])

    def test_coarse_category_and_classification_match_evaluator(self):
        for product in SAMPLE_PRODUCTS:
            values = [str(v) for v in product["categories"]]
            self.assertEqual(um.coarse_category(values), ev.coarse_category(values))
        for value in ("cotton", "color: black", "budget around $20", "Rubber sole", "Department: Womens"):
            self.assertEqual(um.classify_constraint(value), ev.classify_constraint(value))

    def test_simulate_reply_matches_evaluator(self):
        product = SAMPLE_PRODUCTS[0]
        card = ev.intent_card(product)
        constraints = [*card["hard_constraints"], *card["soft_preferences"]]
        types = [um.classify_constraint(c) for c in constraints]
        sample = {"scenario_type": "buying", "intent_card": card}
        for attribute in um.ALLOWED_ATTRIBUTES:
            disclosed_ev: set[str] = set()
            message, _ = ev.customer_reply(sample, attribute, disclosed_ev, True)
            predicted = um.simulate_reply(constraints, types, attribute, frozenset())
            if predicted:
                expected = "For that, what matters is: " + um.render_reply(predicted) + "."
                self.assertEqual(message, expected, attribute)
            else:
                self.assertTrue(message.startswith("I don't have an additional preference"), attribute)

    def test_reply_payload_is_not_split_on_ambiguous_separator(self):
        # 约束原文里本来就含有 "; "，切分会切错，因此解析必须保留整段载荷。
        payload = "Solid colors: 100% Cotton; Heather Grey: 90% Cotton, 10% Polyester"
        kind, parsed, strict = um.parse_reply(f"For that, what matters is: {payload}.")
        self.assertEqual(kind, "disclose")
        self.assertTrue(strict)
        self.assertEqual(parsed, payload)


class OpeningParseTest(unittest.TestCase):
    def test_three_templates_are_distinguished(self):
        cases = [
            ("I'm looking for Men Socks, but I'm still exploring.", um.SCENARIO_BROWSING, "Men Socks", ""),
            ("I'm looking for Men Socks. A key requirement is: wool.", um.SCENARIO_BUYING, "Men Socks", "wool"),
            ("I'm looking for Men Socks. Cushioned footbed", um.SCENARIO_OVERRIDE, "Men Socks", "Cushioned footbed"),
        ]
        for message, scenario, category, constraint in cases:
            got_scenario, got_category, got_constraint, strict = um.parse_opening(message)
            self.assertTrue(strict)
            self.assertEqual((got_scenario, got_category, got_constraint), (scenario, category, constraint))

    def test_paraphrased_opening_is_flagged_not_guessed(self):
        scenario, _, _, strict = um.parse_opening("Hey, I'm shopping for Men Socks — just browsing.")
        self.assertFalse(strict)
        self.assertEqual(scenario, um.SCENARIO_UNKNOWN)


class StoppingRuleTest(unittest.TestCase):
    """记分规则决定了：宁可多等一轮，也不要为了凑数把候选往后排。"""

    def test_waiting_one_turn_is_cheaper_than_dropping_one_rank(self):
        self.assertAlmostEqual(turn_utility(1, 1) - turn_utility(1, 2), 0.02, places=9)
        self.assertAlmostEqual(turn_utility(1, 1) - turn_utility(2, 1), 0.15, places=9)

    def test_plentiful_turns_produce_one_guess_per_turn(self):
        # 剩余轮次充足时，最优计划是每轮只押一个，而不是一次交一堆。
        _value, schedule = endgame_plan([0.4, 0.3, 0.2, 0.1], turn=1)
        self.assertEqual(schedule, [(1, 1), (2, 1), (3, 1), (4, 1)])

    def test_last_turn_dumps_everything(self):
        _value, schedule = endgame_plan([0.4, 0.3, 0.2], turn=10)
        self.assertEqual(schedule, [(10, 1), (10, 2), (10, 3)])

    def test_sequential_plan_beats_a_single_batch(self):
        probs = [0.4, 0.3, 0.2, 0.1]
        sequential, _ = endgame_plan(probs, turn=1)
        batch = sum(p * turn_utility(i + 1, 1) for i, p in enumerate(probs))
        self.assertGreater(sequential, batch)


class AgentBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = write_catalog(SAMPLE_PRODUCTS)
        cls.index = CatalogIndex(cls.path)

    @classmethod
    def tearDownClass(cls):
        Path(cls.path).unlink(missing_ok=True)

    def make_agent(self):
        return Agent(index=self.index)

    def test_response_shape_is_contract_compliant(self):
        agent = self.make_agent()
        agent.reset("s1", {"preference_tags": ["comfort"]})
        out = agent.respond("s1", "I'm looking for Men Socks, but I'm still exploring.", 1, 10)
        self.assertIsInstance(out["message"], str)
        self.assertTrue(out["ask_attribute"] is None or out["ask_attribute"] in um.ALLOWED_ATTRIBUTES)
        self.assertIsInstance(out["recommendations"], list)
        self.assertLessEqual(len(out["recommendations"]), 10)
        for item in out["recommendations"]:
            self.assertIn(item["parent_asin"], {p["parent_asin"] for p in SAMPLE_PRODUCTS})

    def test_holds_back_the_long_tail_early(self):
        # 信息还在流入时，不该把 Top-10 一次性倒出来。
        agent = self.make_agent()
        agent.reset("s2", {})
        out = agent.respond("s2", "I'm looking for Men Socks, but I'm still exploring.", 1, 10)
        self.assertLessEqual(len(out["recommendations"]), 2)

    def test_override_session_withholds_until_new_intent_arrives(self):
        agent = self.make_agent()
        agent.reset("s3", {})
        opening = "I'm looking for Men Socks. Cushioned footbed"
        first = agent.respond("s3", opening, 1, 10)
        # 覆盖到达前命中不会被记录，所以这两轮应该全部用来提问。
        self.assertEqual(first["recommendations"], [])
        self.assertIsNotNone(first["ask_attribute"])

    def test_missed_recommendation_is_excluded_afterwards(self):
        agent = self.make_agent()
        agent.reset("s4", {})
        first = agent.respond("s4", "I'm looking for Men Socks, but I'm still exploring.", 1, 10)
        shown = {item["parent_asin"] for item in first["recommendations"]}
        self.assertTrue(shown)
        second = agent.respond("s4", "For that, what matters is: wool.", 2, 10)
        again = {item["parent_asin"] for item in second["recommendations"]}
        self.assertFalse(shown & again, "a product that already missed cannot be the target")

    def test_paraphrased_conversation_still_produces_candidates(self):
        agent = self.make_agent()
        agent.reset("s5", {})
        out = agent.respond("s5", "Hey! I'm after Men Socks, nothing decided yet.", 1, 10)
        self.assertIsInstance(out["recommendations"], list)
        out2 = agent.respond("s5", "What matters to me: Cushioned footbed", 2, 10)
        self.assertTrue(out2["recommendations"], "fallback must never leave the belief empty")

    def test_unknown_session_id_does_not_raise(self):
        agent = self.make_agent()
        out = agent.respond("never-reset", "I'm looking for Men Socks, but I'm still exploring.", 1, 10)
        self.assertIsInstance(out["message"], str)


if __name__ == "__main__":
    unittest.main()
