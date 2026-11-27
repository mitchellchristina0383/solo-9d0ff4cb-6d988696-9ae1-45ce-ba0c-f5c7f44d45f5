"""页面初始演练数据，以及表单原始值（文本）与视图行之间的转换。"""
from __future__ import annotations

from typing import List


def seed_view() -> dict:
    """一组内置演练场景：含重复策略、被包含策略与不可删的隔离策略。"""
    return {
        "pods": [
            {"name": "web1", "labels_text": "app=web, tier=frontend"},
            {"name": "web2", "labels_text": "app=web, tier=frontend"},
            {"name": "api1", "labels_text": "app=api, tier=backend"},
            {"name": "api2", "labels_text": "app=api, tier=backend"},
            {"name": "db1", "labels_text": "app=db, tier=backend"},
            {"name": "ops1", "labels_text": "app=ops, tier=ops"},
        ],
        "policies": [
            {
                "name": "p-web-ingress-dup-a",
                "selector_text": "app=web",
                "ingress": True,
                "egress": False,
                "ingress_peers_text": "tier=frontend",
                "egress_peers_text": "",
                "deletable": True,
            },
            {
                "name": "p-web-ingress-dup-b",
                "selector_text": "app=web",
                "ingress": True,
                "egress": False,
                "ingress_peers_text": "tier=frontend",
                "egress_peers_text": "",
                "deletable": True,
            },
            {
                "name": "p-web-ingress-wide",
                "selector_text": "app=web",
                "ingress": True,
                "egress": False,
                "ingress_peers_text": "app=web",
                "egress_peers_text": "",
                "deletable": True,
            },
            {
                "name": "p-api-ingress",
                "selector_text": "app=api",
                "ingress": True,
                "egress": False,
                "ingress_peers_text": "app=web",
                "egress_peers_text": "",
                "deletable": False,
            },
            {
                "name": "p-db-ingress",
                "selector_text": "app=db",
                "ingress": True,
                "egress": False,
                "ingress_peers_text": "app=api",
                "egress_peers_text": "",
                "deletable": False,
            },
            {
                "name": "p-backend-egress",
                "selector_text": "tier=backend",
                "ingress": False,
                "egress": True,
                "ingress_peers_text": "",
                "egress_peers_text": "app=api\napp=db",
                "deletable": False,
            },
            {
                "name": "p-web-egress-a",
                "selector_text": "app=web",
                "ingress": False,
                "egress": True,
                "ingress_peers_text": "",
                "egress_peers_text": "tier=backend",
                "deletable": True,
            },
            {
                "name": "p-web-egress-b",
                "selector_text": "app=web",
                "ingress": False,
                "egress": True,
                "ingress_peers_text": "",
                "egress_peers_text": "app=api\napp=db",
                "deletable": True,
            },
        ],
    }


def _indices(form: dict, prefix: str) -> List[int]:
    return sorted(
        {int(key.rsplit("_", 1)[1]) for key in form if key.startswith(prefix)}
    )


def view_from_form(form: dict) -> dict:
    """保留用户在页面上输入的原始文本，用于校验失败或清理后重新渲染。"""
    pods = []
    for i in _indices(form, "pod_name_"):
        pods.append(
            {
                "name": form.get(f"pod_name_{i}") or "",
                "labels_text": form.get(f"pod_labels_{i}") or "",
            }
        )
    policies = []
    for i in _indices(form, "policy_name_"):
        policies.append(
            {
                "name": form.get(f"policy_name_{i}") or "",
                "selector_text": form.get(f"policy_selector_{i}") or "",
                "ingress": bool(form.get(f"policy_ingress_{i}")),
                "egress": bool(form.get(f"policy_egress_{i}")),
                "ingress_peers_text": form.get(f"policy_ingress_peers_{i}") or "",
                "egress_peers_text": form.get(f"policy_egress_peers_{i}") or "",
                "deletable": bool(form.get(f"policy_deletable_{i}")),
            }
        )
    return {"pods": pods, "policies": policies}
