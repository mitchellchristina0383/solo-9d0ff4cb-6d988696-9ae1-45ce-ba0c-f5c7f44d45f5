"""NetworkPolicy 等价清理求解器。

演练范围（按需求简化）：
- 单命名空间内的 Pod，标签选择器只支持等值匹配 (key=value)；
- 忽略端口、IP 段、命名空间选择器等；
- Pod 在某方向没有被任何策略选中时，该方向默认放行；
- 被选中时，取所有选中策略允许对端的并集；
- 两 Pod 连通须同时满足发端出站 (egress) 与收端入站 (ingress)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Sequence, Tuple

Labels = Dict[str, str]
Requirement = Tuple[str, str]


@dataclass
class Policy:
    """一条演练用 NetworkPolicy。

    pod_selector: 作用于 Pod 的等值标签要求，空列表表示选中本命名空间全部 Pod。
    ingress_peers / egress_peers: 对端选择器列表，每个对端选择器是一组等值标签
    要求；空列表表示该方向没有任何允许对端（即选中即拒绝）。
    """

    name: str
    pod_selector: List[Requirement]
    ingress: bool
    egress: bool
    ingress_peers: List[List[Requirement]] = field(default_factory=list)
    egress_peers: List[List[Requirement]] = field(default_factory=list)


def selector_matches(labels: Labels, requirements: Sequence[Requirement]) -> bool:
    """等值标签选择：labels 必须包含全部 key=value 要求。"""
    return all(labels.get(key) == value for key, value in requirements)


def direction_allowed(
    pods: Dict[str, Labels],
    policies: Sequence[Policy],
    pod: str,
    other: str,
    direction: str,
) -> bool:
    """判断 pod 在指定方向上到 other 是否放行。

    direction 取 "ingress" 或 "egress"。没有任何该方向策略选中 pod 时默认放行；
    一旦被选中，取各策略对端选择器的并集。
    """
    selected_any = False
    for policy in policies:
        if direction == "ingress" and not policy.ingress:
            continue
        if direction == "egress" and not policy.egress:
            continue
        if not selector_matches(pods[pod], policy.pod_selector):
            continue
        selected_any = True
        peer_selectors = (
            policy.ingress_peers if direction == "ingress" else policy.egress_peers
        )
        for peer_requirements in peer_selectors:
            if selector_matches(pods[other], peer_requirements):
                return True
    # 未被任何该方向策略选中 => 默认放行；被选中但并集里没有 other => 拒绝
    return not selected_any


def can_connect(
    pods: Dict[str, Labels],
    policies: Sequence[Policy],
    source: str,
    destination: str,
) -> bool:
    """连通须同时满足发端出站和收端入站。"""
    egress_ok = direction_allowed(pods, policies, source, destination, "egress")
    ingress_ok = direction_allowed(pods, policies, destination, source, "ingress")
    return egress_ok and ingress_ok


def connectivity_matrix(
    pods: Dict[str, Labels], policies: Sequence[Policy]
) -> Tuple[List[str], Dict[Tuple[str, str], bool]]:
    """计算全部有序 Pod 对（含自身对）的连通矩阵。"""
    names = list(pods.keys())
    matrix: Dict[Tuple[str, str], bool] = {}
    for source in names:
        for destination in names:
            matrix[(source, destination)] = can_connect(
                pods, policies, source, destination
            )
    return names, matrix


def solve(
    pods: Dict[str, Labels],
    policies: Sequence[Policy],
    deletable: Sequence[bool],
) -> dict:
    """在仅勾选可删的策略中，找数量最多的一组可整体删除且连通性不变的策略。

    策略数上限为 10，候选子集至多 2**10 = 1024 个，直接穷举。
    同数量多组等价时按策略名字典序取第一个，保证结果确定可复现。
    返回删除前后的连通矩阵，便于页面逐对核对。
    """
    names, before = connectivity_matrix(pods, policies)
    candidate_indices = [i for i, flag in enumerate(deletable) if flag]

    best_indices: List[int] = []
    after = before
    for size in range(len(candidate_indices), 0, -1):
        combos = sorted(
            combinations(candidate_indices, size),
            key=lambda combo: tuple(policies[i].name for i in combo),
        )
        for combo in combos:
            removed = set(combo)
            kept = [policy for i, policy in enumerate(policies) if i not in removed]
            _, trial_matrix = connectivity_matrix(pods, kept)
            if trial_matrix == before:
                best_indices = list(combo)
                after = trial_matrix
                break
        if best_indices:
            break

    removed_set = set(best_indices)
    return {
        "pod_names": names,
        "before": before,
        "after": after,
        "removed_indices": best_indices,
        "removed_names": [policies[i].name for i in best_indices],
        "kept_policies": [
            policy for i, policy in enumerate(policies) if i not in removed_set
        ],
        "equivalent": before == after,
    }
