"""把网页表单解析成 solver 使用的结构，并做输入校验。"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .solver import Labels, Policy

MAX_POLICIES = 10
_KEY_RE = re.compile(r"^(?:[a-z0-9]([-a-z0-9_.]*[a-z0-9])?/)?[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")
_VALUE_RE = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$|^$")
_NAME_RE = re.compile(r"^[a-z0-9A-Z][a-z0-9A-Z_.-]{0,62}$")


class FormError(ValueError):
    """带行号信息的表单错误。"""


def _parse_label_block(text: str, location: str) -> List[Tuple[str, str]]:
    """解析 key=value,key=value 形式的标签块，空文本表示空选择器（全选）。"""
    requirements: List[Tuple[str, str]] = []
    text = (text or "").strip()
    if not text:
        return requirements
    for part in text.split(","):
        token = part.strip()
        if "=" not in token:
            raise FormError(f"{location}：标签 “{token}” 必须写成 key=value")
        key, value = token.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            raise FormError(f"{location}：标签键不能为空")
        if not _KEY_RE.match(key):
            raise FormError(f"{location}：标签键 “{key}” 不合法")
        if not _VALUE_RE.match(value):
            raise FormError(f"{location}：标签值 “{value}” 不合法")
        if any(existing_key == key for existing_key, _ in requirements):
            raise FormError(f"{location}：标签键 “{key}” 重复")
        requirements.append((key, value))
    return requirements


def _parse_peer_block(text: str, location: str) -> List[List[Tuple[str, str]]]:
    """解析对端选择器：每行一个选择器，行内用逗号分隔多个等值标签。

    空行忽略；一行留空（整体为空文本）表示空对端列表，即没有允许对端。
    单独一行 “*” 表示空选择器，即选中所有 Pod。
    """
    peers: List[List[Tuple[str, str]]] = []
    for line_no, raw_line in enumerate((text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line == "*":
            peers.append([])
            continue
        peers.append(_parse_label_block(line, f"{location} 第 {line_no} 行"))
    return peers


def parse_form(form: dict) -> Tuple[Dict[str, Labels], List[Policy], List[bool]]:
    """解析整页表单。

    表单字段（下标由前端在提交时重新编号，保证连续）：
    pod_name_<i>, pod_labels_<i>
    policy_name_<i>, policy_selector_<i>, policy_ingress_<i>,
    policy_egress_<i>, policy_ingress_peers_<i>, policy_egress_peers_<i>,
    policy_deletable_<i>
    """
    pod_indices = sorted(
        {int(k.rsplit("_", 1)[1]) for k in form if k.startswith("pod_name_")}
    )
    policy_indices = sorted(
        {int(k.rsplit("_", 1)[1]) for k in form if k.startswith("policy_name_")}
    )

    pods: Dict[str, Labels] = {}
    for i in pod_indices:
        name = (form.get(f"pod_name_{i}") or "").strip()
        labels_text = form.get(f"pod_labels_{i}") or ""
        if not name and not labels_text.strip():
            continue  # 整行空白，忽略
        if not name:
            raise FormError(f"第 {i + 1} 个 Pod：名称不能为空")
        if not _NAME_RE.match(name):
            raise FormError(f"Pod “{name}”：名称仅允许字母数字及 _.- 且长度不超过 63")
        if name in pods:
            raise FormError(f"Pod 名称 “{name}” 重复")
        pods[name] = dict(_parse_label_block(labels_text, f"Pod “{name}” 的标签"))

    if not pods:
        raise FormError("至少需要录入 1 个 Pod")

    if len(policy_indices) > MAX_POLICIES:
        raise FormError(f"策略最多 {MAX_POLICIES} 条，当前有 {len(policy_indices)} 条")

    policies: List[Policy] = []
    deletable: List[bool] = []
    for i in policy_indices:
        name = (form.get(f"policy_name_{i}") or "").strip()
        if not name:
            raise FormError(f"第 {i + 1} 条策略：名称不能为空")
        if not _NAME_RE.match(name):
            raise FormError(
                f"策略 “{name}”：名称仅允许字母数字及 _.- 且长度不超过 63"
            )
        if any(policy.name == name for policy in policies):
            raise FormError(f"策略名称 “{name}” 重复")

        selector = _parse_label_block(
            form.get(f"policy_selector_{i}") or "", f"策略 “{name}” 的 Pod 选择器"
        )
        ingress_enabled = bool(form.get(f"policy_ingress_{i}"))
        egress_enabled = bool(form.get(f"policy_egress_{i}"))
        if not ingress_enabled and not egress_enabled:
            raise FormError(f"策略 “{name}”：至少要启用入站或出站中的一个方向")

        ingress_peers = _parse_peer_block(
            form.get(f"policy_ingress_peers_{i}") or "",
            f"策略 “{name}” 的入站对端",
        )
        egress_peers = _parse_peer_block(
            form.get(f"policy_egress_peers_{i}") or "",
            f"策略 “{name}” 的出站对端",
        )

        policies.append(
            Policy(
                name=name,
                pod_selector=selector,
                ingress=ingress_enabled,
                egress=egress_enabled,
                ingress_peers=ingress_peers,
                egress_peers=egress_peers,
            )
        )
        deletable.append(bool(form.get(f"policy_deletable_{i}")))

    if not policies:
        raise FormError("至少需要录入 1 条策略")

    return pods, policies, deletable
