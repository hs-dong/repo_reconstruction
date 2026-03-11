"""
还原 repo：从快照 + diff 变更序列还原完整仓库
"""

import os
import json
import copy
import re
from typing import Dict, List, Tuple, Optional


def load_jsonl(file_path: str) -> List[Dict]:
    """加载 jsonl 文件，每行一个 JSON 对象"""
    items = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _parse_hunk_header(header: str) -> Tuple[int, int, int, int]:
    """解析 unified diff 的 hunk header: @@ -start,count +start,count @@"""
    match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header)
    if not match:
        raise ValueError(f"Invalid hunk header: {header}")
    old_start = int(match.group(1))
    old_count = int(match.group(2)) if match.group(2) else 1
    new_start = int(match.group(3))
    new_count = int(match.group(4)) if match.group(4) else 1
    return old_start, old_count, new_start, new_count


def apply_diff(base_content: str, diff_text: str) -> str:
    """根据基准内容和 unified diff 文本还原出最新内容"""
    if not diff_text.strip():
        return base_content

    base_lines = base_content.splitlines(keepends=True)
    if base_lines and not base_lines[-1].endswith('\n'):
        base_lines[-1] += '\n'

    diff_lines = diff_text.splitlines(keepends=True)

    hunks: List[Tuple[int, int, List[str]]] = []
    current_hunk = None

    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('@@'):
            if current_hunk:
                hunks.append(current_hunk)
            old_start, old_count, _, _ = _parse_hunk_header(line)
            current_hunk = (old_start, old_count, [])
            continue
        if current_hunk is None:
            continue
        if line.startswith(' '):
            current_hunk[2].append(line[1:])
        elif line.startswith('+'):
            current_hunk[2].append(line[1:])
        elif line.startswith('-'):
            pass
        elif line.startswith('\\'):
            pass

    if current_hunk:
        hunks.append(current_hunk)

    result_lines = list(base_lines)
    for old_start, old_count, new_lines in reversed(hunks):
        start_idx = old_start - 1
        end_idx = start_idx + old_count
        result_lines[start_idx:end_idx] = new_lines

    result = "".join(result_lines)
    if base_content and not base_content.endswith('\n') and result.endswith('\n'):
        result = result[:-1]
    return result


def reposhot_refresh(repo: Dict, diffs: List[Dict]) -> Dict:
    """
    根据起点仓库快照和变更序列还原最新的仓库状态
    （逻辑与 api.py 中的 reposhot_refresh 一致）
    """
    current_repo = copy.deepcopy(repo)
    repo_infos = current_repo.get("repo_infos", {})

    for diff_item in diffs:
        results = diff_item.get("results", [])
        for result in results:
            op_type = result.get("op_type")
            file_path = result.get("file_path")
            diff_content = result.get("diff", "")

            try:
                if op_type == "delete":
                    if file_path in repo_infos:
                        del repo_infos[file_path]
                elif op_type in ["update", "edit", "write", "replace"]:
                    base_content = repo_infos.get(file_path, "")
                    if diff_content:
                        new_content = apply_diff(base_content, diff_content)
                        repo_infos[file_path] = new_content
                else:
                    print(f"[WARN] Unknown op_type: {op_type} for file: {file_path}")
            except Exception as e:
                print(f"[ERROR] Failed to apply diff for {file_path}: {e}")
                continue

    current_repo["repo_infos"] = repo_infos
    return current_repo


def load_reposhot(reposhot_base: str, trigger_date: str, user_id: str, request_id: str) -> Dict:
    """
    加载快照文件。支持两种目录结构：
    1. {base}/{date}/{user_id}/{request_id}.jsonl
    2. {base}/{date}/{request_id}.jsonl (无 user_id 子目录)
    """
    # 优先尝试有 user_id 子目录的路径
    target_file = os.path.join(reposhot_base, trigger_date, user_id, request_id + ".jsonl")
    if not os.path.exists(target_file):
        # 退而求其次，尝试无 user_id 的路径
        target_file = os.path.join(reposhot_base, trigger_date, request_id + ".jsonl")

    if not os.path.exists(target_file):
        print(f"[WARN] Reposhot not found for user={user_id}, request={request_id}")
        return {}

    with open(target_file, 'r', encoding='utf-8') as f:
        reposhot = json.load(f)
    print(f"[INFO] Loaded reposhot from: {target_file}, files={len(reposhot.get('repo_infos', {}))}")
    return reposhot


def load_changes(changes_base: str, trigger_date: str, user_id: str, request_id: str) -> List[Dict]:
    """
    加载 diff 变更序列
    目录结构: {base}/{date}/{user_id}/{request_id}/*.jsonl
    """
    changes_dir = os.path.join(changes_base, trigger_date, user_id, request_id)
    if not os.path.exists(changes_dir):
        print(f"[WARN] Changes dir not found: {changes_dir}")
        return []

    all_changes = []
    for fname in sorted(os.listdir(changes_dir)):
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(changes_dir, fname)
        try:
            changes = load_jsonl(fpath)
            all_changes.extend(changes)
        except Exception as e:
            print(f"[ERROR] Failed to load {fpath}: {e}")

    # 按 timestamp 排序
    all_changes.sort(key=lambda x: x.get("timestamp", 0))
    print(f"[INFO] Loaded {len(all_changes)} change items for request={request_id}")
    return all_changes


def restore_repo(reposhot_base: str, changes_base: str, trigger_date: str,
                 user_id: str, request_id: str) -> Dict:
    """
    完整还原一个 repo：加载快照 + 按顺序应用所有 diff 变更
    
    Returns:
        Dict: {"repo_infos": {file_path: content, ...}, ...} 还原后的仓库
    """
    reposhot = load_reposhot(reposhot_base, trigger_date, user_id, request_id)
    if not reposhot:
        return {}

    diffs = load_changes(changes_base, trigger_date, user_id, request_id)
    if not diffs:
        print(f"[INFO] No changes found, returning raw reposhot")
        return reposhot

    restored = reposhot_refresh(reposhot, diffs)
    print(f"[INFO] Restored repo: {len(restored.get('repo_infos', {}))} files")
    return restored
