"""
分析指定用户的所有 request，对比 diff 前后与真实仓库的相似度变化，
找出哪些 request 的 diff 有效增加了仓库相似度。

使用方式:
    python analyze_user_requests.py \
        --results_file /ai_train/bingodong/dhs/repo_evaluate/eval_script/echocraft_results.txt \
        --user_id 2e1fb58b-ffa3-487f-86a6-eb613f42bc65 \
        --actual_repo_path /ai_train/bingodong/dhs/repo_evaluate/eval_data/EchoCraft

    # 生成 HTML 可视化报告
    python analyze_user_requests.py \
        --results_file /ai_train/bingodong/dhs/repo_evaluate/eval_script/echocraft_results.txt \
        --user_id 2e1fb58b-ffa3-487f-86a6-eb613f42bc65 \
        --actual_repo_path /ai_train/bingodong/dhs/repo_evaluate/eval_data/EchoCraft \
        --html
"""

import argparse
import json
import sys
import os
from typing import Dict, List, Tuple

from restore import load_reposhot, load_changes, reposhot_refresh
from compare import load_actual_repo, compare_repos_before_after
from visualize import generate_html_report


def parse_results_file(results_file: str, target_user_id: str) -> List[Tuple[str, str, str]]:
    """
    从 results.txt 中解析出指定用户的所有 (trigger_date, user_id, request_id)

    Returns:
        List of (trigger_date, user_id, request_id)
    """
    entries = []
    with open(results_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('搜索') or line.startswith('匹配') or line.startswith('涉及') or line.startswith('=') or line.startswith('详细'):
                continue
            parts = line.split('\t')
            if len(parts) != 3:
                continue
            trigger_date, user_id, request_id = parts
            if user_id == target_user_id:
                entries.append((trigger_date, user_id, request_id))
    return entries


def analyze_single_request(
    trigger_date: str,
    user_id: str,
    request_id: str,
    actual_files: Dict[str, str],
    reposhot_base: str,
    changes_base: str,
    generate_html: bool = False,
    html_output_dir: str = "",
) -> Dict:
    """
    分析单个 request 的 diff 是否有效
    
    Args:
        generate_html: 是否生成 HTML 可视化报告
        html_output_dir: HTML 报告输出目录（按 user_id 分子文件夹存放）
    """
    result = {
        "trigger_date": trigger_date,
        "user_id": user_id,
        "request_id": request_id,
        "status": "unknown",
    }

    # 加载快照
    reposhot = load_reposhot(reposhot_base, trigger_date, user_id, request_id)
    if not reposhot or not reposhot.get("repo_infos"):
        result["status"] = "no_reposhot"
        return result

    before_infos = reposhot.get("repo_infos", {})
    workspace_path = reposhot.get("workspace_path", "")
    repo_name = reposhot.get("repo_name", "")
    result["repo_name"] = repo_name
    result["files_in_before"] = len(before_infos)

    # 加载 diff
    diffs = load_changes(changes_base, trigger_date, user_id, request_id)
    result["num_changes"] = len(diffs)

    if diffs:
        restored = reposhot_refresh(reposhot, diffs)
    else:
        restored = reposhot

    after_infos = restored.get("repo_infos", {})
    result["files_in_after"] = len(after_infos)

    # 检查 diff 是否实际改变了文件
    if before_infos == after_infos:
        result["status"] = "no_effective_diff"
        result["has_effective_diff"] = False
    else:
        result["has_effective_diff"] = True

    # before/after 对比
    ba = compare_repos_before_after(before_infos, after_infos, actual_files, workspace_path)

    result["before_avg_similarity"] = ba["before_avg_similarity"]
    result["after_avg_similarity"] = ba["after_avg_similarity"]
    result["avg_similarity_delta"] = ba["avg_similarity_delta"]
    result["improved_files"] = ba["improved_files"]
    result["degraded_files"] = ba["degraded_files"]
    result["added_by_diff"] = ba["added_by_diff"]
    result["removed_by_diff"] = ba["removed_by_diff"]
    result["modified_by_diff"] = ba["modified_by_diff"]
    result["missing_in_actual"] = ba["missing_in_actual"]

    # 分类
    if ba["avg_similarity_delta"] > 1e-6:
        result["status"] = "improved"
    elif ba["avg_similarity_delta"] < -1e-6:
        result["status"] = "degraded"
    elif result.get("has_effective_diff"):
        result["status"] = "no_sim_change"
    else:
        result["status"] = "no_effective_diff"

    # 记录被改善和退化的文件详情
    changed_files = []
    for d in ba["file_details"]:
        if d["diff_action"] in ("modified", "added", "removed"):
            changed_files.append({
                "file": d["rel_path"],
                "action": d["diff_action"],
                "before_sim": d.get("before_similarity", 0.0),
                "after_sim": d.get("after_similarity", 0.0),
                "delta": d.get("delta", 0.0),
                "trend": d.get("trend", ""),
                "missing": d.get("status") == "missing_in_actual",
            })
    result["changed_files"] = changed_files

    # 生成 HTML 可视化报告
    if generate_html and html_output_dir:
        # 按 user_id 创建子文件夹
        user_html_dir = os.path.join(html_output_dir, user_id)
        os.makedirs(user_html_dir, exist_ok=True)
        
        html_path = os.path.join(user_html_dir, f"diff_{request_id[:12]}.html")
        html_content = generate_html_report(
            after_infos, actual_files, workspace_path,
            repo_name=repo_name,
            metadata={
                'trigger_date': trigger_date,
                'user_id': user_id,
                'request_id': request_id,
            },
        )
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        result["html_report"] = html_path
        print(f"    [HTML] Saved to: {html_path}")

    return result


def main():
    parser = argparse.ArgumentParser(description="分析指定用户所有 request 的 diff 有效性")
    parser.add_argument("--results_file", type=str, required=True,
                        help="echocraft_results.txt 的路径")
    parser.add_argument("--user_id", type=str, required=True,
                        help="要分析的用户 ID")
    parser.add_argument("--actual_repo_path", type=str, required=True,
                        help="实际仓库路径")
    parser.add_argument("--reposhot_base", type=str,
                        default="/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos",
                        help="快照文件根目录")
    parser.add_argument("--changes_base", type=str,
                        default="/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes",
                        help="变更文件根目录")
    parser.add_argument("--output", type=str, default="",
                        help="输出 JSON 文件路径（可选，默认保存到 diff_log 目录）")
    parser.add_argument("--html", action="store_true",
                        help="生成 HTML 可视化对比报告（左右对比，标注差异）")
    parser.add_argument("--html_output_dir", type=str,
                        default="/ai_train/bingodong/dhs/repo_evaluate/eval_script/result/visual",
                        help="HTML 报告输出目录（默认按 user_id 创建子文件夹）")
    parser.add_argument("--json_output_dir", type=str,
                        default="/ai_train/bingodong/dhs/repo_evaluate/eval_script/result/diff_log",
                        help="JSON 结果输出目录")
    args = parser.parse_args()

    # 1. 解析目标用户的所有 request
    entries = parse_results_file(args.results_file, args.user_id)
    print(f"[INFO] Found {len(entries)} requests for user {args.user_id}")
    if not entries:
        print("[ERROR] No entries found for this user")
        return

    # 2. 加载实际仓库（只加载一次）
    print(f"[INFO] Loading actual repo from: {args.actual_repo_path}")
    actual_files = load_actual_repo(args.actual_repo_path)
    print(f"[INFO] Actual repo: {len(actual_files)} files")

    # 3. 准备 HTML 输出目录
    html_output_dir = ""
    if args.html:
        html_output_dir = args.html_output_dir
        os.makedirs(html_output_dir, exist_ok=True)
        print(f"[INFO] HTML reports will be saved to: {html_output_dir}/{args.user_id}/")

    # 4. 逐个分析
    all_results = []
    for i, (trigger_date, user_id, request_id) in enumerate(entries):
        print(f"\n[{i+1}/{len(entries)}] {trigger_date} / {request_id[:12]}...")
        result = analyze_single_request(
            trigger_date, user_id, request_id,
            actual_files, args.reposhot_base, args.changes_base,
            generate_html=args.html,
            html_output_dir=html_output_dir,
        )
        all_results.append(result)

    # 5. 汇总输出
    print("\n" + "=" * 100)
    print(f"ANALYSIS SUMMARY: user={args.user_id}, total requests={len(all_results)}")
    print("=" * 100)

    # 按状态分类
    improved = [r for r in all_results if r["status"] == "improved"]
    degraded = [r for r in all_results if r["status"] == "degraded"]
    no_change = [r for r in all_results if r["status"] == "no_sim_change"]
    no_diff = [r for r in all_results if r["status"] == "no_effective_diff"]
    no_repo = [r for r in all_results if r["status"] == "no_reposhot"]

    print(f"\nRequest classification:")
    print(f"  Improved (delta > 0):      {len(improved)}")
    print(f"  Degraded (delta < 0):      {len(degraded)}")
    print(f"  No sim change (delta = 0): {len(no_change)}")
    print(f"  No effective diff:         {len(no_diff)}")
    print(f"  No reposhot found:         {len(no_repo)}")

    # 展示 improved 的详情
    if improved:
        print(f"\n{'─' * 100}")
        print(f"IMPROVED REQUESTS ({len(improved)}):")
        print(f"{'─' * 100}")
        print(f"  {'Date':<10} {'RequestID':<36} {'Before':>8} {'After':>8} {'Delta':>8}  Changed Files")
        print(f"  {'─'*8}   {'─'*34}   {'─'*6}   {'─'*6}   {'─'*6}  {'─'*30}")
        for r in sorted(improved, key=lambda x: -x["avg_similarity_delta"]):
            changed_summary = []
            for cf in r.get("changed_files", []):
                marker = "+" if cf["trend"] == "improved" else ("-" if cf["trend"] == "degraded" else "=")
                changed_summary.append(f"{marker}{os.path.basename(cf['file'])}")
            print(f"  {r['trigger_date']:<10} {r['request_id']:<36} "
                  f"{r['before_avg_similarity']:>7.4f}  "
                  f"{r['after_avg_similarity']:>7.4f}  "
                  f"{r['avg_similarity_delta']:>+7.4f}  "
                  f"{', '.join(changed_summary[:5])}")

    # 展示 degraded 的详情
    if degraded:
        print(f"\n{'─' * 100}")
        print(f"DEGRADED REQUESTS ({len(degraded)}):")
        print(f"{'─' * 100}")
        print(f"  {'Date':<10} {'RequestID':<36} {'Before':>8} {'After':>8} {'Delta':>8}  Changed Files")
        print(f"  {'─'*8}   {'─'*34}   {'─'*6}   {'─'*6}   {'─'*6}  {'─'*30}")
        for r in sorted(degraded, key=lambda x: x["avg_similarity_delta"]):
            changed_summary = []
            for cf in r.get("changed_files", []):
                marker = "+" if cf["trend"] == "improved" else ("-" if cf["trend"] == "degraded" else "=")
                changed_summary.append(f"{marker}{os.path.basename(cf['file'])}")
            print(f"  {r['trigger_date']:<10} {r['request_id']:<36} "
                  f"{r['before_avg_similarity']:>7.4f}  "
                  f"{r['after_avg_similarity']:>7.4f}  "
                  f"{r['avg_similarity_delta']:>+7.4f}  "
                  f"{', '.join(changed_summary[:5])}")

    # 整体统计
    effective = [r for r in all_results if r.get("has_effective_diff")]
    if effective:
        avg_delta = sum(r["avg_similarity_delta"] for r in effective) / len(effective)
        print(f"\n{'─' * 100}")
        print(f"Overall stats (only requests with effective diff):")
        print(f"  Total effective: {len(effective)}")
        print(f"  Average delta:   {avg_delta:+.4f}")
        print(f"  Improvement rate: {len(improved)}/{len(effective)} = {len(improved)/len(effective)*100:.1f}%")

    # 6. 保存 JSON 结果
    # 确保 JSON 输出目录存在
    os.makedirs(args.json_output_dir, exist_ok=True)
    
    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(
            args.json_output_dir,
            f"analysis_{args.user_id[:8]}.json"
        )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] Detailed results saved to: {output_path}")

    # 7. 输出 HTML 报告汇总信息
    if args.html:
        html_count = sum(1 for r in all_results if r.get("html_report"))
        user_html_dir = os.path.join(args.html_output_dir, args.user_id)
        print(f"[INFO] Generated {html_count} HTML reports in: {user_html_dir}")


if __name__ == "__main__":
    main()
