"""求解器语义测试：默认放行、并集、双向门、最大等价删除组与平局规则。"""
import unittest

from app.solver import (
    Policy,
    can_connect,
    connectivity_matrix,
    selector_matches,
    solve,
)


def policy(name, selector, ingress=False, egress=False, in_peers=None, out_peers=None):
    return Policy(
        name=name,
        pod_selector=selector,
        ingress=ingress,
        egress=egress,
        ingress_peers=in_peers or [],
        egress_peers=out_peers or [],
    )


class SelectorTest(unittest.TestCase):
    def test_empty_selector_matches_everything(self):
        self.assertTrue(selector_matches({"app": "x"}, []))
        self.assertTrue(selector_matches({}, []))

    def test_equality_requires_all_pairs(self):
        reqs = [("app", "web"), ("tier", "fe")]
        self.assertTrue(selector_matches({"app": "web", "tier": "fe", "x": "y"}, reqs))
        self.assertFalse(selector_matches({"app": "web"}, reqs))
        self.assertFalse(selector_matches({"app": "web", "tier": "be"}, reqs))


class ConnectivityTest(unittest.TestCase):
    def setUp(self):
        # a, b, c 三个 Pod；无策略时全部互通（含自身对）
        self.pods = {
            "a": {"app": "web"},
            "b": {"app": "api"},
            "c": {"app": "db"},
        }

    def test_no_policy_allows_everything_by_default(self):
        _, matrix = connectivity_matrix(self.pods, [])
        self.assertTrue(all(matrix.values()))

    def test_ingress_selecting_destination_is_default_deny_without_matching_peer(self):
        # 只给 c 加入站策略，允许对端 app=api
        policies = [
            policy("c-in", [("app", "db")], ingress=True, in_peers=[[("app", "api")]])
        ]
        # b -> c：c 的入站允许 b（api），双方出站都无策略默认放行 => 通
        self.assertTrue(can_connect(self.pods, policies, "b", "c"))
        # a -> c：c 的入站不允许 a（web） => 断
        self.assertFalse(can_connect(self.pods, policies, "a", "c"))
        # a -> b 不受影响，双方方向均无策略选中 => 通
        self.assertTrue(can_connect(self.pods, policies, "a", "b"))

    def test_egress_and_ingress_must_both_allow(self):
        policies = [
            # b 只接受 a
            policy("b-in", [("app", "api")], ingress=True, in_peers=[[("app", "web")]]),
            # a 只允许访问 c
            policy("a-out", [("app", "web")], egress=True, out_peers=[[("app", "db")]]),
        ]
        # a -> b：a 的出站不允许 b => 断（即使 b 入站允许 a）
        self.assertFalse(can_connect(self.pods, policies, "a", "b"))
        # a -> c：a 出站允许 c，c 入站无策略默认放行 => 通
        self.assertTrue(can_connect(self.pods, policies, "a", "c"))
        # b -> c：b 出站默认放行，但 c 入站无策略；均放行 => 通
        self.assertTrue(can_connect(self.pods, policies, "b", "c"))

    def test_union_of_peers_across_policies(self):
        policies = [
            policy(
                "c-in-1",
                [("app", "db")],
                ingress=True,
                in_peers=[[("app", "api")]],
            ),
            policy(
                "c-in-2",
                [("app", "db")],
                ingress=True,
                in_peers=[[("app", "web")]],
            ),
        ]
        # 两条策略的对端取并集：api 和 web 都能访问 c
        self.assertTrue(can_connect(self.pods, policies, "b", "c"))
        self.assertTrue(can_connect(self.pods, policies, "a", "c"))

    def test_empty_peer_list_means_selected_but_deny(self):
        policies = [policy("lock", [("app", "db")], ingress=True, in_peers=[])]
        self.assertFalse(can_connect(self.pods, policies, "b", "c"))
        self.assertFalse(can_connect(self.pods, policies, "a", "c"))
        # c 自身对自身：入站被选中且无允许对端 => 断
        self.assertFalse(can_connect(self.pods, policies, "c", "c"))

    def test_wildcard_peer_selector(self):
        policies = [
            policy("c-in", [("app", "db")], ingress=True, in_peers=[[]]),
        ]
        self.assertTrue(can_connect(self.pods, policies, "a", "c"))
        self.assertTrue(can_connect(self.pods, policies, "b", "c"))


class SolverTest(unittest.TestCase):
    def setUp(self):
        self.pods = {
            "a": {"app": "web"},
            "b": {"app": "api"},
            "c": {"app": "db"},
        }

    def test_duplicate_policy_is_removable(self):
        duplicate = lambda name: policy(
            name, [("app", "db")], ingress=True, in_peers=[[("app", "api")]]
        )
        # 不可删锚点与重复项同选择器、同对端，保证删光重复项后不会回落默认放行
        anchor = policy("anchor", [("app", "db")], ingress=True,
                        in_peers=[[("app", "api")]])
        policies = [duplicate("dup-a"), duplicate("dup-b"), anchor]
        result = solve(self.pods, policies, [True, True, False])
        self.assertEqual(result["removed_indices"], [0, 1])
        self.assertTrue(result["equivalent"])

    def test_solver_picks_largest_equivalent_subset(self):
        # 宽策略（不可删锚点）允许全部，两条窄策略分别允许 api/web。
        # 锚点与窄策略作用于同一组 Pod，避免删光后回落默认放行
        wide = policy("wide-anchor", [("app", "db")], ingress=True, in_peers=[[]])
        narrow1 = policy("narrow-api", [("app", "db")], ingress=True,
                         in_peers=[[("app", "api")]])
        narrow2 = policy("narrow-web", [("app", "db")], ingress=True,
                         in_peers=[[("app", "web")]])
        policies = [wide, narrow1, narrow2]
        result = solve(self.pods, policies, [False, True, True])
        # 两条窄策略都是宽策略的子集，可同时删；宽策略不能和它们一起删
        self.assertEqual(sorted(result["removed_names"]), ["narrow-api", "narrow-web"])
        self.assertTrue(result["equivalent"])

    def test_non_deletable_policies_are_never_removed(self):
        keep = policy("keep", [("app", "db")], ingress=True,
                      in_peers=[[("app", "api")]])
        dup = policy("dup", [("app", "db")], ingress=True,
                     in_peers=[[("app", "api")]])
        result = solve(self.pods, [keep, dup], [False, True])
        self.assertEqual(result["removed_names"], ["dup"])

    def test_no_safe_removal_returns_empty(self):
        only = policy("only", [("app", "db")], ingress=True,
                      in_peers=[[("app", "api")]])
        result = solve(self.pods, [only], [True])
        self.assertEqual(result["removed_names"], [])
        self.assertEqual(result["kept_policies"], [only])

    def test_tie_break_is_lexicographic_by_name(self):
        # 三条完全等价的重复策略，最多只能删 2 条；平局时按名字字典序取
        mk = lambda name: policy(
            name, [("app", "db")], ingress=True, in_peers=[[("app", "api")]]
        )
        policies = [mk("zeta"), mk("alpha"), mk("mid")]
        result = solve(self.pods, policies, [True, True, True])
        self.assertEqual(result["removed_names"], ["alpha", "mid"])

    def test_max_ten_policies_exhaustive(self):
        # 10 条完全等价策略：任意 9 条可删，第 10 条必须保留
        mk = lambda idx: policy(
            f"p{idx:02d}", [("app", "db")], ingress=True,
            in_peers=[[("app", "api")]],
        )
        policies = [mk(i) for i in range(10)]
        result = solve(self.pods, policies, [True] * 10)
        self.assertEqual(len(result["removed_names"]), 9)
        self.assertTrue(result["equivalent"])

    def test_matrix_unchanged_for_removal(self):
        lock = policy("lock", [("app", "db")], ingress=True, in_peers=[])
        # 不可删出站锚点与两条可删重复项同选择器、同对端：
        # 重复项可全部删除（锚点继续维持效果），但 lock 一旦删掉隔离就消失
        anchor = policy("eg-anchor", [("app", "web")], egress=True, out_peers=[[]])
        dup = policy("dup", [("app", "web")], egress=True, out_peers=[[]])
        dup2 = policy("dup2", [("app", "web")], egress=True, out_peers=[[]])
        result = solve(self.pods, [lock, anchor, dup, dup2],
                       [True, False, True, True])
        # lock 不可删（删了 c 的隔离就没了）；两条等价出站策略都可由锚点兜底
        self.assertNotIn("lock", result["removed_names"])
        self.assertEqual(sorted(result["removed_names"]), ["dup", "dup2"])
        self.assertEqual(result["before"], result["after"])
        # 隔离效果保留：没有对端能访问 c
        self.assertFalse(result["after"][("a", "c")])
        self.assertFalse(result["after"][("b", "c")])


if __name__ == "__main__":
    unittest.main()
