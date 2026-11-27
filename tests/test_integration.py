"""解析器校验与 Flask 端到端测试（含批量删除、求解时改标签场景）。"""
import unittest

from app import create_app
from app.parser import FormError, parse_form
from app.seed import seed_view


def form_from_view(view):
    """把视图行展开成提交后的扁平表单（下标连续）。"""
    form = {}
    for i, pod in enumerate(view["pods"]):
        form[f"pod_name_{i}"] = pod["name"]
        form[f"pod_labels_{i}"] = pod["labels_text"]
    for i, policy in enumerate(view["policies"]):
        form[f"policy_name_{i}"] = policy["name"]
        form[f"policy_selector_{i}"] = policy["selector_text"]
        form[f"policy_ingress_peers_{i}"] = policy["ingress_peers_text"]
        form[f"policy_egress_peers_{i}"] = policy["egress_peers_text"]
        if policy["ingress"]:
            form[f"policy_ingress_{i}"] = "on"
        if policy["egress"]:
            form[f"policy_egress_{i}"] = "on"
        if policy["deletable"]:
            form[f"policy_deletable_{i}"] = "on"
    return form


class ParserTest(unittest.TestCase):
    def test_wildcard_and_multiline_peers(self):
        view = {
            "pods": [{"name": "p1", "labels_text": "app=web"}],
            "policies": [
                {
                    "name": "pol",
                    "selector_text": "",
                    "ingress": True,
                    "egress": True,
                    "ingress_peers_text": "*\napp=web, tier=fe",
                    "egress_peers_text": "",
                    "deletable": False,
                }
            ],
        }
        pods, policies, deletable = parse_form(form_from_view(view))
        self.assertEqual(pods, {"p1": {"app": "web"}})
        pol = policies[0]
        self.assertEqual(pol.pod_selector, [])  # 空选择器 = 全选
        self.assertEqual(pol.ingress_peers, [[], [("app", "web"), ("tier", "fe")]])
        self.assertEqual(pol.egress_peers, [])  # 留空 = 无允许对端
        self.assertEqual(deletable, [False])

    def test_bad_label_syntax_rejected(self):
        view = {
            "pods": [{"name": "p1", "labels_text": "appweb"}],
            "policies": [
                {
                    "name": "pol",
                    "selector_text": "",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "*",
                    "egress_peers_text": "",
                    "deletable": False,
                }
            ],
        }
        with self.assertRaises(FormError):
            parse_form(form_from_view(view))

    def test_direction_required(self):
        view = {
            "pods": [{"name": "p1", "labels_text": "app=web"}],
            "policies": [
                {
                    "name": "pol",
                    "selector_text": "",
                    "ingress": False,
                    "egress": False,
                    "ingress_peers_text": "",
                    "egress_peers_text": "",
                    "deletable": False,
                }
            ],
        }
        with self.assertRaises(FormError):
            parse_form(form_from_view(view))

    def test_duplicate_names_and_empty_rows(self):
        view = {
            "pods": [
                {"name": "p1", "labels_text": "app=a"},
                {"name": "", "labels_text": ""},  # 空白行应被忽略
                {"name": "p1", "labels_text": "app=b"},
            ],
            "policies": [
                {
                    "name": "pol",
                    "selector_text": "",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "*",
                    "egress_peers_text": "",
                    "deletable": False,
                }
            ],
        }
        with self.assertRaises(FormError):
            parse_form(form_from_view(view))

    def test_more_than_ten_policies_rejected(self):
        view = {
            "pods": [{"name": "p1", "labels_text": "app=web"}],
            "policies": [
                {
                    "name": f"pol{i}",
                    "selector_text": "",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "*",
                    "egress_peers_text": "",
                    "deletable": False,
                }
                for i in range(11)
            ],
        }
        with self.assertRaises(FormError):
            parse_form(form_from_view(view))


class WebFlowTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_index_renders_seed(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("NetworkPolicy 清理演练".encode(), resp.data)
        self.assertIn("p-web-ingress-dup-a".encode(), resp.data)

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})

    def test_clean_seed_removes_three_redundant_policies(self):
        """种子场景的端到端清理：两组重复 + 一组等价对端，共删 3 条。"""
        form = form_from_view(seed_view())
        resp = self.client.post("/clean", data=form)
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        for name in ("p-web-ingress-dup-a", "p-web-ingress-dup-b", "p-web-egress-a"):
            self.assertIn(name, body)
        # 未勾选可删的策略不会出现在删除清单里
        for name in ("p-api-ingress", "p-db-ingress", "p-backend-egress"):
            self.assertNotIn(f"{name}</strong>", body)
        # 页面保留全部录入行，被删的行带徽标
        self.assertIn("本次已删除", body)
        # 矩阵两栏都在，且没有差异高亮（CSS 中定义了 td.diff，故按 class 出现判断）
        self.assertIn("删除前", body)
        self.assertIn("删除后", body)
        self.assertNotIn('class="no diff"', body)
        self.assertNotIn('class="yes diff"', body)

    def test_batch_delete_only_checked_policies(self):
        """成批删除：只勾选两条重复入站策略，其它策略不受影响。"""
        view = seed_view()
        for policy in view["policies"]:
            policy["deletable"] = policy["name"] in {
                "p-web-ingress-dup-a",
                "p-web-ingress-dup-b",
            }
        resp = self.client.post("/clean", data=form_from_view(view))
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("p-web-ingress-dup-a", body)
        self.assertIn("p-web-ingress-dup-b", body)
        # 未勾选的等价出站策略不能被动到
        self.assertNotIn("p-web-egress-a</strong>", body)
        self.assertIn("实际删除 2 条策略", body)

    def test_relabel_during_solving_changes_result(self):
        """求解时改标签：同一批策略、同一组勾选，标签一变，可删集合随之变化。"""
        view = seed_view()
        resp_before = self.client.post("/clean", data=form_from_view(view))
        self.assertIn("实际删除 3 条策略".encode(), resp_before.data)
        self.assertIn("p-web-egress-a</strong>".encode(), resp_before.data)

        # 把 web2 改成 tier=backend：出站组中两条策略对 web2 的允许集合
        # 不再相同（backend 宽 vs api/db 窄），等价关系被打破，删除集合换名
        for pod in view["pods"]:
            if pod["name"] == "web2":
                pod["labels_text"] = "app=web, tier=backend"
        resp_after = self.client.post("/clean", data=form_from_view(view))
        self.assertEqual(resp_after.status_code, 200)
        body = resp_after.data.decode()
        # 入站重复对仍然可删，但出站组改删 egress-b（按字典序的等价项）
        self.assertIn("p-web-egress-b</strong>", body)
        self.assertNotIn("p-web-egress-a</strong>", body)
        # 标签修改在重渲染的录入区保留，证明求解时页面仍可改标签
        self.assertIn("app=web, tier=backend", body)

    def test_relabel_can_make_policies_essential(self):
        """求解时改 Pod 标签：同一组策略与勾选，可删数量从 2 降为 1。"""
        view = {
            "pods": [
                {"name": "w1", "labels_text": "app=web"},
                {"name": "w2", "labels_text": "app=web"},
                {"name": "d1", "labels_text": "app=db"},
                # 初始标签不匹配任何对端选择器
                {"name": "o1", "labels_text": "app=ops"},
            ],
            "policies": [
                # 不可删锚点：只允许 app=web 访问 db
                {
                    "name": "db-in-anchor",
                    "selector_text": "app=db",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "app=web",
                    "egress_peers_text": "",
                    "deletable": False,
                },
                # 两条可删策略：a 与锚点完全重复；b 额外允许 app=other（初始无此标签 Pod，冗余）
                {
                    "name": "db-in-a",
                    "selector_text": "app=db",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "app=web",
                    "egress_peers_text": "",
                    "deletable": True,
                },
                {
                    "name": "db-in-b",
                    "selector_text": "app=db",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "app=web\napp=other",
                    "egress_peers_text": "",
                    "deletable": True,
                },
            ],
        }
        # 初始没有 app=other 的 Pod，b 的第二个对端选择器匹配不到任何 Pod，
        # a、b 对现有矩阵都是冗余，两条都能删
        resp_dup = self.client.post("/clean", data=form_from_view(view))
        self.assertIn("实际删除 2 条策略".encode(), resp_dup.data)

        # 求解时把 o1 的标签改成 app=other：b 变成唯一允许 o1 访问 d1 的策略，
        # 不再可删；只剩与锚点重复的 a 可删
        view["pods"][3]["labels_text"] = "app=other"
        resp_relabel = self.client.post("/clean", data=form_from_view(view))
        self.assertEqual(resp_relabel.status_code, 200)
        self.assertIn("实际删除 1 条策略".encode(), resp_relabel.data)
        self.assertIn("db-in-a</strong>", resp_relabel.data.decode())
        self.assertIn("app=other", resp_relabel.data.decode())

    def test_form_error_returns_400_and_keeps_input(self):
        view = seed_view()
        view["pods"][0]["labels_text"] = "bad-label"
        resp = self.client.post("/clean", data=form_from_view(view))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("输入有误".encode(), resp.data)
        self.assertIn("bad-label".encode(), resp.data)

    def test_no_safe_removal(self):
        view = {
            "pods": [
                {"name": "a", "labels_text": "app=web"},
                {"name": "b", "labels_text": "app=db"},
            ],
            "policies": [
                {
                    "name": "only",
                    "selector_text": "app=db",
                    "ingress": True,
                    "egress": False,
                    "ingress_peers_text": "app=web",
                    "egress_peers_text": "",
                    "deletable": True,
                }
            ],
        }
        resp = self.client.post("/clean", data=form_from_view(view))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("没有找到可安全删除的策略组".encode(), resp.data)


if __name__ == "__main__":
    unittest.main()
