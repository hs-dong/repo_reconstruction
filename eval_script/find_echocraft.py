#!/usr/bin/env python3
"""
分析 /data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos 路径下
哪些文件包含 "EchoCraft"，并输出对应的日期和用户ID。

文件路径结构：
/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos/{日期}/{用户ID}/{request_id}.jsonl
"""

import os
import subprocess
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# 配置
BASE_DIR = Path("/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output")
SEARCH_KEYWORD = "EchoCraft"


def search_file_for_keyword(filepath: Path, keyword: str) -> bool:
    """检查文件是否包含指定关键字"""
    try:
        result = subprocess.run(
            ["grep", "-q", keyword, str(filepath)],
            capture_output=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def parse_filepath(filepath: Path) -> dict:
    """
    从文件路径解析日期、用户ID和请求ID
    路径格式: .../repos/{日期}/{用户ID}/{request_id}.jsonl
    """
    parts = filepath.parts
    try:
        # 找到 'repos' 在路径中的位置
        repos_idx = parts.index('repos')
        date = parts[repos_idx + 1]       # 日期，如 20260131
        user_id = parts[repos_idx + 2]    # 用户ID，如 1e3ccbf4-9e21-44ae-9d86-dbbd4e0fc6d4
        request_id = filepath.stem        # 请求ID，如 1d5e2fbbfaf2495dbf80bac5d6a0dc95
        return {
            "date": date,
            "user_id": user_id,
            "request_id": request_id,
            "filepath": str(filepath)
        }
    except (ValueError, IndexError):
        return None


def find_all_jsonl_files(base_dir: Path) -> list:
    """查找所有 .jsonl 文件"""
    files = []
    for root, dirs, filenames in os.walk(base_dir):
        for filename in filenames:
            if filename.endswith('.jsonl'):
                files.append(Path(root) / filename)
    return files


def main():
    print(f"搜索路径: {BASE_DIR}")
    print(f"搜索关键字: {SEARCH_KEYWORD}")
    print("-" * 60)
    
    # 1. 查找所有 .jsonl 文件
    print("正在扫描文件...")
    all_files = find_all_jsonl_files(BASE_DIR)
    print(f"共找到 {len(all_files)} 个 .jsonl 文件")
    
    # 2. 并行搜索包含关键字的文件
    matching_files = []
    print(f"\n正在搜索包含 '{SEARCH_KEYWORD}' 的文件...")
    
    with ThreadPoolExecutor(max_workers=16) as executor:
        future_to_file = {
            executor.submit(search_file_for_keyword, f, SEARCH_KEYWORD): f 
            for f in all_files
        }
        
        for future in tqdm(as_completed(future_to_file), total=len(all_files), desc="搜索进度"):
            filepath = future_to_file[future]
            try:
                if future.result():
                    matching_files.append(filepath)
            except Exception as e:
                print(f"处理 {filepath} 时出错: {e}")
    
    # 3. 解析并汇总结果
    results_by_user = defaultdict(lambda: {"dates": set(), "request_ids": [], "files": []})
    
    for filepath in matching_files:
        parsed = parse_filepath(filepath)
        if parsed:
            user_id = parsed["user_id"]
            results_by_user[user_id]["dates"].add(parsed["date"])
            results_by_user[user_id]["request_ids"].append(parsed["request_id"])
            results_by_user[user_id]["files"].append(parsed["filepath"])
    
    # 4. 输出结果
    print("\n" + "=" * 60)
    print(f"搜索结果: 共找到 {len(matching_files)} 个包含 '{SEARCH_KEYWORD}' 的文件")
    print(f"涉及 {len(results_by_user)} 个不同的用户ID")
    print("=" * 60)
    
    # 按用户ID输出详细信息
    for i, (user_id, info) in enumerate(sorted(results_by_user.items()), 1):
        print(f"\n[{i}] 用户ID: {user_id}")
        print(f"    日期: {', '.join(sorted(info['dates']))}")
        print(f"    文件数量: {len(info['files'])}")
        print(f"    请求ID列表:")
        for req_id in info['request_ids'][:5]:  # 最多显示5个
            print(f"      - {req_id}")
        if len(info['request_ids']) > 5:
            print(f"      ... 还有 {len(info['request_ids']) - 5} 个")
    
    # 5. 汇总表格
    print("\n" + "=" * 60)
    print("汇总表格 (日期 -> 用户ID)")
    print("=" * 60)
    
    date_user_map = defaultdict(set)
    for user_id, info in results_by_user.items():
        for date in info['dates']:
            date_user_map[date].add(user_id)
    
    for date in sorted(date_user_map.keys()):
        print(f"\n日期 {date}:")
        for user_id in date_user_map[date]:
            file_count = sum(1 for f in matching_files if user_id in str(f) and date in str(f))
            print(f"  - {user_id} ({file_count} 个文件)")
    
    # 6. 保存详细结果到文件
    output_file = Path(__file__).parent / "echocraft_results.txt"
    with open(output_file, "w") as f:
        f.write(f"搜索关键字: {SEARCH_KEYWORD}\n")
        f.write(f"搜索路径: {BASE_DIR}\n")
        f.write(f"匹配文件数: {len(matching_files)}\n")
        f.write(f"涉及用户数: {len(results_by_user)}\n")
        f.write("\n" + "=" * 60 + "\n")
        f.write("详细文件列表:\n")
        for filepath in sorted(matching_files):
            parsed = parse_filepath(filepath)
            if parsed:
                f.write(f"{parsed['date']}\t{parsed['user_id']}\t{parsed['request_id']}\n")
    
    print(f"\n详细结果已保存到: {output_file}")


if __name__ == "__main__":
    main()
