"""
对比还原后的 repo 与实际 repo 的差异
"""

import os
import difflib
from typing import Dict, List, Tuple


def load_actual_repo(repo_path: str) -> Dict[str, str]:
    """
    加载本地实际 repo 的所有文件内容
    
    Args:
        repo_path: 实际 repo 的根目录路径
        
    Returns:
        Dict[str, str]: {relative_path: content, ...}
    """
    file_map = {}
    for root, dirs, files in os.walk(repo_path):
        # 跳过隐藏目录 (.git, .vscode 等)
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if fname.startswith('.'):
                continue
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, repo_path)
            try:
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_map[rel_path] = f.read()
            except Exception:
                # 跳过无法读取的文件（如二进制文件）
                pass
    return file_map


def compute_similarity(content_a: str, content_b: str) -> float:
    """
    计算两段文本的相似度 (0.0 ~ 1.0)
    使用 difflib.SequenceMatcher
    """
    if content_a == content_b:
        return 1.0
    if not content_a and not content_b:
        return 1.0
    if not content_a or not content_b:
        return 0.0
    return difflib.SequenceMatcher(None, content_a, content_b).ratio()


def generate_unified_diff(file_path: str, content_a: str, content_b: str, n: int = 3) -> str:
    """生成 unified diff 文本"""
    lines_a = content_a.splitlines(keepends=True)
    lines_b = content_b.splitlines(keepends=True)
    diff = difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"restored/{file_path}",
        tofile=f"actual/{file_path}",
        n=n
    )
    return "".join(diff)


def compare_repos(restored_repo_infos: Dict[str, str],
                  actual_file_map: Dict[str, str],
                  workspace_path: str = "") -> Dict:
    """
    将还原后的 repo 与实际 repo 做文件级对比
    
    只比较还原 repo 中存在的文件（以还原 repo 为基准），在实际 repo 中查找对应文件。
    
    还原 repo 中的文件路径可能带有 repo 名前缀（如 "EchoCraft/src/main.py"），
    需要去掉前缀后才能与实际 repo 的 relative path 匹配。
    
    Args:
        restored_repo_infos: 还原 repo 的 {file_path: content}
        actual_file_map: 实际 repo 的 {relative_path: content}
        workspace_path: 还原 repo 中 file_path 的 workspace 前缀（用于去除）
        
    Returns:
        Dict: 对比结果
    """
    results = {
        "total_restored_files": len(restored_repo_infos),
        "matched_files": 0,
        "missing_in_actual": 0,
        "identical_files": 0,
        "different_files": 0,
        "total_similarity": 0.0,
        "file_details": [],
    }

    # 确定还原 repo 文件路径的前缀
    # 还原 repo 的 key 形如 "repo_name/path/to/file" 或直接是 "path/to/file"
    # 需要自动识别并去除前缀
    prefix = _detect_prefix(restored_repo_infos.keys(), actual_file_map.keys(), workspace_path)

    for restored_path, restored_content in sorted(restored_repo_infos.items()):
        # 去除前缀，得到在实际 repo 中的相对路径
        rel_path = _strip_prefix(restored_path, prefix)

        if rel_path not in actual_file_map:
            results["missing_in_actual"] += 1
            results["file_details"].append({
                "file": restored_path,
                "rel_path": rel_path,
                "status": "missing_in_actual",
                "similarity": 0.0,
            })
            continue

        results["matched_files"] += 1
        actual_content = actual_file_map[rel_path]
        similarity = compute_similarity(restored_content, actual_content)
        results["total_similarity"] += similarity

        if similarity == 1.0:
            results["identical_files"] += 1
            results["file_details"].append({
                "file": restored_path,
                "rel_path": rel_path,
                "status": "identical",
                "similarity": 1.0,
            })
        else:
            results["different_files"] += 1
            diff_text = generate_unified_diff(rel_path, restored_content, actual_content)
            results["file_details"].append({
                "file": restored_path,
                "rel_path": rel_path,
                "status": "different",
                "similarity": round(similarity, 4),
                "diff_preview": diff_text[:2000] if len(diff_text) > 2000 else diff_text,
            })

    matched = results["matched_files"]
    results["avg_similarity"] = round(results["total_similarity"] / matched, 4) if matched > 0 else 0.0

    return results


def _detect_prefix(restored_keys, actual_keys, workspace_path: str = "") -> str:
    """
    自动检测还原 repo 文件路径的前缀
    
    比如还原 repo 的 key 是 "EchoCraft/src/main.py"，
    实际 repo 的 key 是 "src/main.py"，那么前缀是 "EchoCraft/"
    """
    if not restored_keys or not actual_keys:
        return ""

    actual_set = set(actual_keys)

    # 尝试常见前缀：取第一个还原文件路径的第一层目录
    sample_keys = list(restored_keys)[:min(20, len(list(restored_keys)))]

    # 收集候选前缀
    candidate_prefixes = set()
    candidate_prefixes.add("")  # 无前缀

    for key in sample_keys:
        parts = key.split("/")
        # 尝试去掉前1、2层目录作为前缀
        for i in range(1, min(3, len(parts))):
            prefix = "/".join(parts[:i]) + "/"
            candidate_prefixes.add(prefix)

    # 如果有 workspace_path，也尝试用它作为前缀
    if workspace_path:
        # workspace_path 可能是完整路径，取最后一个目录名
        ws_name = os.path.basename(workspace_path.rstrip("/"))
        if ws_name:
            candidate_prefixes.add(ws_name + "/")

    # 选择匹配最多文件的前缀
    best_prefix = ""
    best_match_count = 0
    for prefix in candidate_prefixes:
        match_count = 0
        for key in sample_keys:
            stripped = key[len(prefix):] if key.startswith(prefix) else key
            if stripped in actual_set:
                match_count += 1
        if match_count > best_match_count:
            best_match_count = match_count
            best_prefix = prefix

    if best_prefix:
        print(f"[INFO] Detected prefix: '{best_prefix}' (matched {best_match_count}/{len(sample_keys)} sample files)")

    return best_prefix


def _strip_prefix(path: str, prefix: str) -> str:
    """去除路径前缀"""
    if prefix and path.startswith(prefix):
        return path[len(prefix):]
    return path


def compare_repos_before_after(
    before_repo_infos: Dict[str, str],
    after_repo_infos: Dict[str, str],
    actual_file_map: Dict[str, str],
    workspace_path: str = "",
) -> Dict:
    """
    同时对比重建前(before)和重建后(after)与真实仓库(actual)的差异，
    以展示还原过程中新增/修改的内容是否有意义。

    对比维度：
    - 对于 after 中每个文件，计算 before→actual 和 after→actual 的相似度
    - 区分"未变化文件"、"改善文件"、"退化文件"、"新增文件"、"删除文件"

    Args:
        before_repo_infos: 重建前(原始快照)的 {file_path: content}
        after_repo_infos:  重建后(应用diff后)的 {file_path: content}
        actual_file_map:   真实仓库的 {relative_path: content}
        workspace_path:    路径前缀

    Returns:
        Dict: 对比结果
    """
    # 合并所有出现过的文件路径
    all_paths = set(before_repo_infos.keys()) | set(after_repo_infos.keys())

    # 检测前缀（用 after 的 key 集合来检测）
    prefix = _detect_prefix(
        after_repo_infos.keys() if after_repo_infos else before_repo_infos.keys(),
        actual_file_map.keys(),
        workspace_path,
    )

    results = {
        "total_files": len(all_paths),
        "files_in_before": len(before_repo_infos),
        "files_in_after": len(after_repo_infos),
        "added_by_diff": 0,       # diff 新增的文件（before 无，after 有）
        "removed_by_diff": 0,     # diff 删除的文件（before 有，after 无）
        "modified_by_diff": 0,    # diff 修改过的文件（before/after 都有且内容不同）
        "unchanged_by_diff": 0,   # diff 未改动的文件
        "improved_files": 0,      # after 比 before 更接近 actual
        "degraded_files": 0,      # after 比 before 更远离 actual
        "unchanged_similarity": 0,  # 修改前后相似度不变
        "before_avg_similarity": 0.0,
        "after_avg_similarity": 0.0,
        "avg_similarity_delta": 0.0,
        "missing_in_actual": 0,
        "file_details": [],
    }

    before_sim_sum = 0.0
    after_sim_sum = 0.0
    matched_count = 0

    for path in sorted(all_paths):
        rel_path = _strip_prefix(path, prefix)
        in_before = path in before_repo_infos
        in_after = path in after_repo_infos
        in_actual = rel_path in actual_file_map

        before_content = before_repo_infos.get(path, "")
        after_content = after_repo_infos.get(path, "")
        actual_content = actual_file_map.get(rel_path, "")

        # 确定 diff 操作类型
        if in_before and in_after:
            if before_content == after_content:
                diff_action = "unchanged"
                results["unchanged_by_diff"] += 1
            else:
                diff_action = "modified"
                results["modified_by_diff"] += 1
        elif not in_before and in_after:
            diff_action = "added"
            results["added_by_diff"] += 1
        elif in_before and not in_after:
            diff_action = "removed"
            results["removed_by_diff"] += 1
        else:
            continue

        if not in_actual:
            results["missing_in_actual"] += 1
            results["file_details"].append({
                "file": path,
                "rel_path": rel_path,
                "diff_action": diff_action,
                "status": "missing_in_actual",
                "before_similarity": 0.0,
                "after_similarity": 0.0,
                "delta": 0.0,
            })
            continue

        matched_count += 1
        before_sim = compute_similarity(before_content, actual_content) if in_before else 0.0
        after_sim = compute_similarity(after_content, actual_content) if in_after else 0.0
        delta = round(after_sim - before_sim, 4)

        before_sim_sum += before_sim
        after_sim_sum += after_sim

        # 判断改善/退化
        if diff_action in ("modified", "added", "removed"):
            if delta > 1e-6:
                trend = "improved"
                results["improved_files"] += 1
            elif delta < -1e-6:
                trend = "degraded"
                results["degraded_files"] += 1
            else:
                trend = "no_change"
                results["unchanged_similarity"] += 1
        else:
            trend = "no_change"
            results["unchanged_similarity"] += 1

        detail = {
            "file": path,
            "rel_path": rel_path,
            "diff_action": diff_action,
            "trend": trend,
            "before_similarity": round(before_sim, 4),
            "after_similarity": round(after_sim, 4),
            "delta": delta,
        }

        # 对有变化且不完全一致的文件，附加 diff 预览
        if diff_action in ("modified", "added") and after_sim < 1.0 and in_actual:
            diff_text = generate_unified_diff(rel_path, after_content, actual_content)
            detail["diff_preview"] = diff_text[:2000] if len(diff_text) > 2000 else diff_text

        results["file_details"].append(detail)

    if matched_count > 0:
        results["before_avg_similarity"] = round(before_sim_sum / matched_count, 4)
        results["after_avg_similarity"] = round(after_sim_sum / matched_count, 4)
        results["avg_similarity_delta"] = round(
            results["after_avg_similarity"] - results["before_avg_similarity"], 4
        )

    return results


def format_before_after_report(results: Dict) -> str:
    """格式化重建前后对比报告"""
    lines = []
    lines.append("=" * 90)
    lines.append("Repo Before/After Comparison Report")
    lines.append("=" * 90)

    lines.append(f"Files in before (snapshot):    {results['files_in_before']}")
    lines.append(f"Files in after  (restored):    {results['files_in_after']}")
    lines.append(f"  - Added by diff:             {results['added_by_diff']}")
    lines.append(f"  - Removed by diff:           {results['removed_by_diff']}")
    lines.append(f"  - Modified by diff:          {results['modified_by_diff']}")
    lines.append(f"  - Unchanged by diff:         {results['unchanged_by_diff']}")
    lines.append(f"Missing in actual repo:        {results['missing_in_actual']}")
    lines.append("")
    lines.append(f"Before avg similarity to actual: {results['before_avg_similarity']:.4f}")
    lines.append(f"After  avg similarity to actual: {results['after_avg_similarity']:.4f}")
    lines.append(f"Similarity delta (after-before): {results['avg_similarity_delta']:+.4f}")
    lines.append("")
    lines.append(f"Improved files  (after closer to actual): {results['improved_files']}")
    lines.append(f"Degraded files  (after farther from actual): {results['degraded_files']}")
    lines.append(f"Unchanged similarity files:               {results['unchanged_similarity']}")

    # 展示被 diff 修改过的文件详情（modified / added / removed）
    changed_details = [
        d for d in results["file_details"]
        if d["diff_action"] in ("modified", "added", "removed")
    ]
    if changed_details:
        lines.append("")
        lines.append("-" * 90)
        lines.append(f"Changed files detail ({len(changed_details)}):")
        lines.append("-" * 90)
        lines.append(f"  {'File':<50} {'Action':<10} {'Before':>8} {'After':>8} {'Delta':>8} {'Trend'}")
        lines.append(f"  {'-'*48}  {'-'*8}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*10}")
        for d in sorted(changed_details, key=lambda x: x.get("delta", 0)):
            trend_marker = {
                "improved": " [+]",
                "degraded": " [-]",
                "no_change": " [=]",
            }.get(d.get("trend", ""), "")
            status_note = " (missing)" if d.get("status") == "missing_in_actual" else ""
            lines.append(
                f"  {d['rel_path']:<50} {d['diff_action']:<10} "
                f"{d.get('before_similarity', 0.0):>7.4f}  "
                f"{d.get('after_similarity', 0.0):>7.4f}  "
                f"{d.get('delta', 0.0):>+7.4f}"
                f"{trend_marker}{status_note}"
            )

    # 退化文件的 diff 预览
    degraded = [d for d in results["file_details"] if d.get("trend") == "degraded" and d.get("diff_preview")]
    if degraded:
        lines.append("")
        lines.append("-" * 90)
        lines.append("Degraded files diff preview (after vs actual):")
        lines.append("-" * 90)
        for d in degraded[:5]:
            lines.append(f"\n  File: {d['rel_path']}  (delta={d['delta']:+.4f})")
            for dl in d["diff_preview"].splitlines()[:15]:
                lines.append(f"    {dl}")

    lines.append("")
    lines.append("=" * 90)
    return "\n".join(lines)


def format_report(results: Dict) -> str:
    """格式化对比报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("Repo Comparison Report")
    lines.append("=" * 80)
    lines.append(f"Total files in restored repo: {results['total_restored_files']}")
    lines.append(f"Matched in actual repo:       {results['matched_files']}")
    lines.append(f"Missing in actual repo:       {results['missing_in_actual']}")
    lines.append(f"Identical files:              {results['identical_files']}")
    lines.append(f"Different files:              {results['different_files']}")
    lines.append(f"Average similarity:           {results['avg_similarity']:.4f}")
    lines.append("")

    # 展示差异文件详情
    diff_files = [d for d in results["file_details"] if d["status"] == "different"]
    if diff_files:
        lines.append("-" * 80)
        lines.append(f"Different files ({len(diff_files)}):")
        lines.append("-" * 80)
        for detail in sorted(diff_files, key=lambda x: x["similarity"]):
            lines.append(f"\n  File: {detail['rel_path']}")
            lines.append(f"  Similarity: {detail['similarity']:.4f}")
            if detail.get("diff_preview"):
                lines.append(f"  Diff preview:")
                for dl in detail["diff_preview"].splitlines()[:20]:
                    lines.append(f"    {dl}")
                if len(detail["diff_preview"].splitlines()) > 20:
                    lines.append(f"    ... (truncated)")

    # 展示缺失文件
    missing_files = [d for d in results["file_details"] if d["status"] == "missing_in_actual"]
    if missing_files:
        lines.append("")
        lines.append("-" * 80)
        lines.append(f"Missing in actual repo ({len(missing_files)}):")
        lines.append("-" * 80)
        for detail in missing_files:
            lines.append(f"  {detail['rel_path']}")

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)
