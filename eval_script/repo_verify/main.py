"""
入口脚本：还原 repo 快照并与实际 repo 对比差异

使用方式:
    # 指定单个快照
    python main.py \
        --trigger_date 20260203 \
        --user_id 00476bdd-44f0-488c-b094-48f3edbdc35f \
        --request_id 420f8a6f33e640d7938a8eef366e54e8 \
        --actual_repo_path /data_fast_v2/changqingai/workspace_code/for_agent_model/EchoCraft

    # 扫描模式：遍历 trigger_date 下所有快照，每个都还原并与 actual_repo 对比
    python main.py \
        --trigger_date 20260203 \
        --actual_repo_path /data_fast_v2/changqingai/workspace_code/for_agent_model/EchoCraft \
        --scan
"""

import argparse
import os
import json

from restore import restore_repo, load_reposhot, load_changes, reposhot_refresh
from compare import (
    load_actual_repo, compare_repos, format_report,
    compare_repos_before_after, format_before_after_report,
)
from visualize import generate_html_report


def run_single(args):
    """对单个 (user_id, request_id) 进行还原与对比"""
    print(f"\n{'='*80}")
    print(f"Processing: user_id={args.user_id}, request_id={args.request_id}")
    print(f"{'='*80}")

    # 1. 加载原始快照 (before)
    reposhot = load_reposhot(args.reposhot_base, args.trigger_date, args.user_id, args.request_id)
    if not reposhot or not reposhot.get("repo_infos"):
        print("[ERROR] Failed to load reposhot or repo is empty")
        return None

    before_infos = reposhot.get("repo_infos", {})
    workspace_path = reposhot.get("workspace_path", "")

    # 2. 应用 diff 得到还原后的 repo (after)
    diffs = load_changes(args.changes_base, args.trigger_date, args.user_id, args.request_id)
    if diffs:
        restored = reposhot_refresh(reposhot, diffs)
    else:
        restored = reposhot

    after_infos = restored.get("repo_infos", {})
    if not after_infos:
        print("[ERROR] Restored repo is empty")
        return None

    # 3. 加载实际 repo
    print(f"[INFO] Loading actual repo from: {args.actual_repo_path}")
    actual_files = load_actual_repo(args.actual_repo_path)
    print(f"[INFO] Actual repo: {len(actual_files)} files")

    # 4. 原有对比（after vs actual）
    results = compare_repos(after_infos, actual_files, workspace_path)
    results["user_id"] = args.user_id
    results["request_id"] = args.request_id
    results["repo_name"] = restored.get("repo_name", "")

    report = format_report(results)
    print(report)

    # 5. before/after 对比
    ba_results = compare_repos_before_after(
        before_infos, after_infos, actual_files, workspace_path
    )
    ba_results["user_id"] = args.user_id
    ba_results["request_id"] = args.request_id
    ba_results["repo_name"] = restored.get("repo_name", "")

    ba_report = format_before_after_report(ba_results)
    print(ba_report)

    results["before_after"] = ba_results

    # 6. 生成 HTML 可视化报告（如果指定了 --html）
    if getattr(args, 'html', False):
        html_output = getattr(args, 'html_output', None)
        if not html_output:
            html_dir = "/ai_train/bingodong/dhs/repo_evaluate/eval_script/result/visual"
            os.makedirs(html_dir, exist_ok=True)
            html_output = os.path.join(
                html_dir,
                f"diff_report_{args.request_id[:12]}.html"
            )
        html_content = generate_html_report(
            after_infos, actual_files, workspace_path,
            repo_name=restored.get("repo_name", ""),
            metadata={
                'trigger_date': args.trigger_date,
                'user_id': args.user_id,
                'request_id': args.request_id,
            },
        )
        with open(html_output, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"\n[INFO] HTML diff report saved to: {html_output}")

    return results


def scan_all(args):
    """扫描指定日期下所有快照，逐个还原并与 actual_repo 对比"""
    repos_date_dir = os.path.join(args.reposhot_base, args.trigger_date)

    if not os.path.exists(repos_date_dir):
        print(f"[ERROR] Repos date dir not found: {repos_date_dir}")
        return

    print(f"[INFO] Loading actual repo from: {args.actual_repo_path}")
    actual_files = load_actual_repo(args.actual_repo_path)
    print(f"[INFO] Actual repo: {len(actual_files)} files")

    all_results = []

    # 遍历目录结构
    for item in sorted(os.listdir(repos_date_dir)):
        item_path = os.path.join(repos_date_dir, item)

        if os.path.isdir(item_path):
            # 目录结构: {user_id}/{request_id}.jsonl
            user_id = item
            for fname in sorted(os.listdir(item_path)):
                if not fname.endswith('.jsonl'):
                    continue
                request_id = fname.replace('.jsonl', '')
                _process_one(args, user_id, request_id, actual_files, all_results)
        elif item.endswith('.jsonl'):
            # 直接在日期目录下: {request_id}.jsonl（无 user_id 子目录）
            request_id = item.replace('.jsonl', '')
            _process_one(args, "", request_id, actual_files, all_results)

    # 汇总报告
    _print_summary(all_results)

    # 保存结果
    if all_results:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Results saved to: {output_path}")


def _process_one(args, user_id: str, request_id: str,
                 actual_files: dict, all_results: list):
    """处理单个快照：加载 -> 应用 diff -> 与实际 repo 对比（含 before/after 对比）"""
    reposhot = load_reposhot(args.reposhot_base, args.trigger_date, user_id, request_id)
    if not reposhot or not reposhot.get("repo_infos"):
        return

    repo_name = reposhot.get("repo_name", "")
    workspace_path = reposhot.get("workspace_path", "")

    print(f"\n{'='*80}")
    print(f"Processing: user_id={user_id}, request_id={request_id}, repo_name={repo_name}")
    print(f"{'='*80}")

    before_infos = reposhot.get("repo_infos", {})

    # 应用 diff 变更
    diffs = load_changes(args.changes_base, args.trigger_date, user_id, request_id)
    if diffs:
        restored = reposhot_refresh(reposhot, diffs)
    else:
        restored = reposhot

    after_infos = restored.get("repo_infos", {})
    if not after_infos:
        return

    # 原有对比（after vs actual）
    results = compare_repos(after_infos, actual_files, workspace_path)
    results["user_id"] = user_id
    results["request_id"] = request_id
    results["repo_name"] = repo_name

    report = format_report(results)
    print(report)

    # before/after 对比（展示 diff 还原是否有意义）
    ba_results = compare_repos_before_after(
        before_infos, after_infos, actual_files, workspace_path
    )
    ba_results["user_id"] = user_id
    ba_results["request_id"] = request_id
    ba_results["repo_name"] = repo_name

    ba_report = format_before_after_report(ba_results)
    print(ba_report)

    results["before_after"] = ba_results
    all_results.append(results)

    # HTML 可视化报告
    if getattr(args, 'html', False):
        html_dir = "/ai_train/bingodong/dhs/repo_evaluate/eval_script/result/visual"
        os.makedirs(html_dir, exist_ok=True)
        html_path = os.path.join(html_dir, f"diff_{request_id[:12]}.html")
        html_content = generate_html_report(
            after_infos, actual_files, workspace_path,
            repo_name=repo_name,
            metadata={
                'trigger_date': args.trigger_date,
                'user_id': user_id,
                'request_id': request_id,
            },
        )
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[INFO] HTML report: {html_path}")


def _print_summary(all_results: list):
    """打印汇总统计"""
    if not all_results:
        print("\n[INFO] No repos processed")
        return

    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(all_results)} repos compared")
    print(f"{'='*80}")

    total_files = sum(r["total_restored_files"] for r in all_results)
    total_matched = sum(r["matched_files"] for r in all_results)
    total_identical = sum(r["identical_files"] for r in all_results)
    total_different = sum(r["different_files"] for r in all_results)
    total_missing = sum(r["missing_in_actual"] for r in all_results)
    avg_sim = sum(r["avg_similarity"] for r in all_results) / len(all_results) if all_results else 0

    print(f"Total restored files:   {total_files}")
    print(f"Total matched:          {total_matched}")
    print(f"Total identical:        {total_identical}")
    print(f"Total different:        {total_different}")
    print(f"Total missing:          {total_missing}")
    print(f"Overall avg similarity: {avg_sim:.4f}")

    # Before/After 汇总
    ba_results = [r["before_after"] for r in all_results if "before_after" in r]
    if ba_results:
        print(f"\n{'─'*80}")
        print("Before/After Summary (diff restoration effectiveness):")
        print(f"{'─'*80}")
        avg_before = sum(r["before_avg_similarity"] for r in ba_results) / len(ba_results)
        avg_after = sum(r["after_avg_similarity"] for r in ba_results) / len(ba_results)
        total_improved = sum(r["improved_files"] for r in ba_results)
        total_degraded = sum(r["degraded_files"] for r in ba_results)
        total_unchanged_sim = sum(r["unchanged_similarity"] for r in ba_results)
        print(f"  Avg similarity before diff: {avg_before:.4f}")
        print(f"  Avg similarity after  diff: {avg_after:.4f}")
        print(f"  Avg delta:                  {avg_after - avg_before:+.4f}")
        print(f"  Total improved files:       {total_improved}")
        print(f"  Total degraded files:       {total_degraded}")
        print(f"  Total unchanged sim files:  {total_unchanged_sim}")

    print(f"\nPer-repo breakdown:")
    for r in all_results:
        ba = r.get("before_after", {})
        ba_str = ""
        if ba:
            ba_str = (f", before_sim={ba.get('before_avg_similarity', 0):.4f}"
                      f", after_sim={ba.get('after_avg_similarity', 0):.4f}"
                      f", delta={ba.get('avg_similarity_delta', 0):+.4f}")
        print(f"  [{r.get('request_id', 'N/A')[:12]}...] "
              f"repo={r.get('repo_name', 'N/A')}, "
              f"files={r['total_restored_files']}, "
              f"matched={r['matched_files']}, "
              f"identical={r['identical_files']}, "
              f"diff={r['different_files']}, "
              f"missing={r['missing_in_actual']}, "
              f"similarity={r['avg_similarity']:.4f}"
              f"{ba_str}")


def main():
    parser = argparse.ArgumentParser(description="还原 repo 快照并与实际 repo 对比差异")
    parser.add_argument("--trigger_date", type=str, required=True,
                        help="触发日期，格式 YYYYMMDD，如 20260203")
    parser.add_argument("--user_id", type=str, default="",
                        help="用户 ID（指定单个快照时使用）")
    parser.add_argument("--request_id", type=str, default="",
                        help="请求 ID（指定单个快照时使用）")
    parser.add_argument("--actual_repo_path", type=str, required=True,
                        help="实际 repo 的本地路径，用于与还原后的 repo 做对比")
    parser.add_argument("--reposhot_base", type=str,
                        default="/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos",
                        help="快照文件根目录")
    parser.add_argument("--changes_base", type=str,
                        default="/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes",
                        help="变更文件根目录")
    parser.add_argument("--scan", action="store_true",
                        help="扫描模式：遍历 trigger_date 下所有快照进行还原和对比")
    parser.add_argument("--html", action="store_true",
                        help="生成 HTML 可视化对比报告（左右对比，标注差异）")
    parser.add_argument("--html_output", type=str, default="",
                        help="HTML 报告输出路径（默认自动生成）")

    args = parser.parse_args()

    if args.scan or (not args.user_id and not args.request_id):
        scan_all(args)
    else:
        if not args.user_id or not args.request_id:
            parser.error("必须同时指定 --user_id 和 --request_id，或使用 --scan 模式")
        run_single(args)


if __name__ == "__main__":
    main()
