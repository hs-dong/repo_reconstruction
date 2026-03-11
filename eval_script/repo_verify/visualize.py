"""
可视化模块：生成 HTML 格式的还原 repo 与实际 repo 的左右对比页面
"""

import os
import html
import difflib
from typing import Dict, List, Tuple


def _escape(text: str) -> str:
    """HTML 转义"""
    return html.escape(text)


def _compute_line_diffs(lines_a: List[str], lines_b: List[str]) -> List[Tuple[str, str, str, str]]:
    """
    逐行对比两个文件，返回对齐后的行列表。
    每个元素为 (left_line, right_line, left_type, right_type)
    type: 'equal', 'added', 'removed', 'modified', 'empty'
    """
    result = []
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                result.append((lines_a[i], lines_b[j], 'equal', 'equal'))
        elif tag == 'replace':
            left_lines = lines_a[i1:i2]
            right_lines = lines_b[j1:j2]
            max_len = max(len(left_lines), len(right_lines))
            for k in range(max_len):
                l_line = left_lines[k] if k < len(left_lines) else ""
                r_line = right_lines[k] if k < len(right_lines) else ""
                l_type = 'modified' if k < len(left_lines) else 'empty'
                r_type = 'modified' if k < len(right_lines) else 'empty'
                result.append((l_line, r_line, l_type, r_type))
        elif tag == 'delete':
            for i in range(i1, i2):
                result.append((lines_a[i], "", 'removed', 'empty'))
        elif tag == 'insert':
            for j in range(j1, j2):
                result.append(("", lines_b[j], 'empty', 'added'))

    return result


def _render_inline_diff(old_line: str, new_line: str) -> Tuple[str, str]:
    """
    对单行内容做字符级 diff，返回带 <span> 高亮的 HTML。
    """
    if not old_line and not new_line:
        return "", ""
    if not old_line:
        return "", f'<span class="char-added">{_escape(new_line)}</span>'
    if not new_line:
        return f'<span class="char-removed">{_escape(old_line)}</span>', ""

    sm = difflib.SequenceMatcher(None, old_line, new_line)
    left_parts = []
    right_parts = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            left_parts.append(_escape(old_line[i1:i2]))
            right_parts.append(_escape(new_line[j1:j2]))
        elif tag == 'replace':
            left_parts.append(f'<span class="char-removed">{_escape(old_line[i1:i2])}</span>')
            right_parts.append(f'<span class="char-added">{_escape(new_line[j1:j2])}</span>')
        elif tag == 'delete':
            left_parts.append(f'<span class="char-removed">{_escape(old_line[i1:i2])}</span>')
        elif tag == 'insert':
            right_parts.append(f'<span class="char-added">{_escape(new_line[j1:j2])}</span>')

    return "".join(left_parts), "".join(right_parts)


def _generate_file_diff_html(file_path: str, content_a: str, content_b: str,
                              similarity: float, status: str) -> str:
    """
    为单个文件生成左右对比 HTML 片段。
    左边 = 还原的 repo (content_a)，右边 = 实际 repo (content_b)
    """
    lines_a = content_a.splitlines() if content_a else []
    lines_b = content_b.splitlines() if content_b else []

    if status == 'identical':
        badge_class = 'badge-identical'
        badge_text = 'IDENTICAL'
    elif status == 'missing_in_actual':
        badge_class = 'badge-missing'
        badge_text = 'MISSING IN ACTUAL'
    elif status == 'only_in_actual':
        badge_class = 'badge-only-actual'
        badge_text = 'ONLY IN ACTUAL'
    else:
        badge_class = 'badge-different'
        badge_text = f'DIFFERENT (sim: {similarity:.4f})'

    is_collapsed = status == 'identical'
    collapsed_class = ' collapsed' if is_collapsed else ''

    parts = []
    parts.append(f'<div class="file-block{collapsed_class}" data-status="{status}">')
    parts.append(f'  <div class="file-header" onclick="toggleFile(this)">')
    parts.append(f'    <span class="file-path">{_escape(file_path)}</span>')
    parts.append(f'    <span class="badge {badge_class}">{badge_text}</span>')
    parts.append(f'    <span class="toggle-icon">{("▶" if is_collapsed else "▼")}</span>')
    parts.append(f'  </div>')
    parts.append(f'  <div class="file-content" style="display: {"none" if is_collapsed else "block"};">')

    if status == 'identical':
        parts.append(f'    <div class="identical-notice">文件内容完全一致（{len(lines_a)} 行）</div>')
    elif status == 'missing_in_actual':
        parts.append(f'    <div class="diff-table-wrapper"><table class="diff-table"><tbody>')
        for i, line in enumerate(lines_a):
            parts.append(
                f'<tr>'
                f'<td class="line-num">{i + 1}</td>'
                f'<td class="line-content line-removed">{_escape(line)}</td>'
                f'<td class="line-num"></td>'
                f'<td class="line-content line-empty"></td>'
                f'</tr>'
            )
        parts.append(f'    </tbody></table></div>')
    elif status == 'only_in_actual':
        parts.append(f'    <div class="diff-table-wrapper"><table class="diff-table"><tbody>')
        for i, line in enumerate(lines_b):
            parts.append(
                f'<tr>'
                f'<td class="line-num"></td>'
                f'<td class="line-content line-empty"></td>'
                f'<td class="line-num">{i + 1}</td>'
                f'<td class="line-content line-added">{_escape(line)}</td>'
                f'</tr>'
            )
        parts.append(f'    </tbody></table></div>')
    else:
        aligned = _compute_line_diffs(lines_a, lines_b)
        parts.append(f'    <div class="diff-table-wrapper"><table class="diff-table"><tbody>')
        left_num = 0
        right_num = 0
        for left_line, right_line, left_type, right_type in aligned:
            if left_type != 'empty':
                left_num += 1
            if right_type != 'empty':
                right_num += 1

            l_num_str = str(left_num) if left_type != 'empty' else ''
            r_num_str = str(right_num) if right_type != 'empty' else ''

            if left_type == 'modified' and right_type == 'modified':
                l_html, r_html = _render_inline_diff(left_line, right_line)
                l_class = 'line-modified'
                r_class = 'line-modified'
            else:
                l_html = _escape(left_line)
                r_html = _escape(right_line)
                l_class = {
                    'equal': 'line-equal',
                    'removed': 'line-removed',
                    'modified': 'line-modified',
                    'empty': 'line-empty',
                }.get(left_type, '')
                r_class = {
                    'equal': 'line-equal',
                    'added': 'line-added',
                    'modified': 'line-modified',
                    'empty': 'line-empty',
                }.get(right_type, '')

            parts.append(
                f'<tr>'
                f'<td class="line-num">{l_num_str}</td>'
                f'<td class="line-content {l_class}">{l_html}</td>'
                f'<td class="line-num">{r_num_str}</td>'
                f'<td class="line-content {r_class}">{r_html}</td>'
                f'</tr>'
            )
        parts.append(f'    </tbody></table></div>')

    parts.append(f'  </div>')
    parts.append(f'</div>')
    return "\n".join(parts)


def generate_html_report(
    restored_repo_infos: Dict[str, str],
    actual_file_map: Dict[str, str],
    workspace_path: str = "",
    repo_name: str = "",
    metadata: Dict = None,
) -> str:
    """
    生成完整的 HTML 对比报告。

    Args:
        restored_repo_infos: 还原 repo 的 {file_path: content}
        actual_file_map: 实际 repo 的 {relative_path: content}
        workspace_path: 路径前缀
        repo_name: 仓库名
        metadata: 额外信息（trigger_date, user_id, request_id 等）

    Returns:
        str: 完整的 HTML 文本
    """
    from compare import _detect_prefix, _strip_prefix, compute_similarity

    prefix = _detect_prefix(restored_repo_infos.keys(), actual_file_map.keys(), workspace_path)

    # 收集所有文件并分类
    file_entries = []
    stats = {
        'total': 0, 'identical': 0, 'different': 0,
        'missing_in_actual': 0, 'only_in_actual': 0,
        'total_similarity': 0.0, 'matched': 0,
    }

    # 还原 repo 中的文件
    restored_rel_map = {}
    for path, content in restored_repo_infos.items():
        rel_path = _strip_prefix(path, prefix)
        restored_rel_map[rel_path] = content

    # 处理还原 repo 的文件
    for rel_path in sorted(restored_rel_map.keys()):
        restored_content = restored_rel_map[rel_path]
        stats['total'] += 1

        if rel_path not in actual_file_map:
            stats['missing_in_actual'] += 1
            file_entries.append({
                'path': rel_path,
                'restored_content': restored_content,
                'actual_content': '',
                'similarity': 0.0,
                'status': 'missing_in_actual',
            })
        else:
            actual_content = actual_file_map[rel_path]
            sim = compute_similarity(restored_content, actual_content)
            stats['matched'] += 1
            stats['total_similarity'] += sim

            if sim == 1.0:
                stats['identical'] += 1
                file_entries.append({
                    'path': rel_path,
                    'restored_content': restored_content,
                    'actual_content': actual_content,
                    'similarity': 1.0,
                    'status': 'identical',
                })
            else:
                stats['different'] += 1
                file_entries.append({
                    'path': rel_path,
                    'restored_content': restored_content,
                    'actual_content': actual_content,
                    'similarity': sim,
                    'status': 'different',
                })

    # 只在实际 repo 中存在的文件 - 只统计数量，不添加到 file_entries
    # 这样可以大幅减小 HTML 文件体积，只显示还原仓库中的文件及其对应的真实仓库文件
    for rel_path in sorted(actual_file_map.keys()):
        if rel_path not in restored_rel_map:
            stats['only_in_actual'] += 1
            # 不再添加到 file_entries，只统计数量

    avg_sim = stats['total_similarity'] / stats['matched'] if stats['matched'] > 0 else 0.0

    # 排序：different 在前，missing 次之，identical 最后（不再包含 only_in_actual）
    status_order = {'different': 0, 'missing_in_actual': 1, 'identical': 2}
    file_entries.sort(key=lambda e: (status_order.get(e['status'], 9), e['path']))

    # 生成文件对比 HTML
    file_htmls = []
    for entry in file_entries:
        file_htmls.append(_generate_file_diff_html(
            entry['path'],
            entry['restored_content'],
            entry['actual_content'],
            entry['similarity'],
            entry['status'],
        ))

    meta = metadata or {}
    title = f"Repo Diff: {repo_name}" if repo_name else "Repo Diff Report"

    html_content = _build_full_html(
        title=title,
        repo_name=repo_name,
        metadata=meta,
        stats=stats,
        avg_sim=avg_sim,
        file_htmls=file_htmls,
        file_entries=file_entries,
    )
    return html_content


def _build_full_html(title, repo_name, metadata, stats, avg_sim, file_htmls, file_entries):
    """组装完整 HTML 页面"""
    meta_info = ""
    if metadata:
        meta_parts = []
        for k in ['trigger_date', 'user_id', 'request_id']:
            if k in metadata:
                meta_parts.append(f'<span class="meta-item"><b>{k}:</b> {_escape(str(metadata[k]))}</span>')
        meta_info = " &nbsp;|&nbsp; ".join(meta_parts)

    files_content = "\n".join(file_htmls)

    # 生成文件列表侧边栏数据
    file_list_items = []
    for entry in file_entries:
        status_icon = {
            'identical': '✓',
            'different': '≠',
            'missing_in_actual': '✗',
            'only_in_actual': '+',
        }.get(entry['status'], '?')
        status_class = entry['status'].replace('_', '-')
        file_list_items.append(
            f'<div class="file-list-item status-{status_class}" '
            f'onclick="scrollToFile(\'{_escape(entry["path"])}\')" '
            f'title="{_escape(entry["path"])}">'
            f'<span class="status-icon">{status_icon}</span>'
            f'<span class="file-name">{_escape(entry["path"])}</span>'
            f'</div>'
        )
    file_list_html = "\n".join(file_list_items)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    display: flex;
    flex-direction: column;
    height: 100vh;
}}

.header {{
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 16px 24px;
    flex-shrink: 0;
}}

.header h1 {{
    font-size: 20px;
    color: #f0f6fc;
    margin-bottom: 8px;
}}

.header .meta {{
    font-size: 13px;
    color: #8b949e;
}}

.meta-item b {{ color: #c9d1d9; }}

.stats-bar {{
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 12px 24px;
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    flex-shrink: 0;
}}

.stat-item {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
}}

.stat-dot {{
    width: 10px; height: 10px; border-radius: 50%;
}}

.stat-dot.identical {{ background: #3fb950; }}
.stat-dot.different {{ background: #d29922; }}
.stat-dot.missing {{ background: #f85149; }}
.stat-dot.only-actual {{ background: #58a6ff; }}

.stat-value {{ font-weight: 600; color: #f0f6fc; }}

.toolbar {{
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 8px 24px;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-shrink: 0;
}}

.toolbar button {{
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    transition: background 0.15s;
}}

.toolbar button:hover {{ background: #30363d; }}
.toolbar button.active {{ background: #388bfd; border-color: #388bfd; color: #fff; }}

.toolbar .search-box {{
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 4px;
}}

.toolbar input[type="text"] {{
    background: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    width: 220px;
}}

.toolbar input[type="text"]::placeholder {{ color: #484f58; }}

.main-container {{
    display: flex;
    flex: 1;
    overflow: hidden;
}}

.sidebar {{
    width: 280px;
    background: #0d1117;
    border-right: 1px solid #30363d;
    overflow-y: auto;
    flex-shrink: 0;
}}

.sidebar-header {{
    padding: 10px 12px;
    font-size: 12px;
    font-weight: 600;
    color: #8b949e;
    border-bottom: 1px solid #21262d;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    position: sticky;
    top: 0;
    background: #0d1117;
    z-index: 1;
}}

.file-list-item {{
    padding: 6px 12px;
    font-size: 12px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    border-bottom: 1px solid #21262d;
    transition: background 0.1s;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}

.file-list-item:hover {{ background: #161b22; }}
.file-list-item .status-icon {{ flex-shrink: 0; font-size: 11px; }}
.file-list-item .file-name {{ overflow: hidden; text-overflow: ellipsis; }}

.status-identical .status-icon {{ color: #3fb950; }}
.status-different .status-icon {{ color: #d29922; }}
.status-missing-in-actual .status-icon {{ color: #f85149; }}
.status-only-in-actual .status-icon {{ color: #58a6ff; }}

.content-area {{
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}}

.file-block {{
    margin-bottom: 16px;
    border: 1px solid #30363d;
    border-radius: 6px;
    overflow: hidden;
}}

.file-header {{
    background: #161b22;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    cursor: pointer;
    user-select: none;
    gap: 10px;
    border-bottom: 1px solid #30363d;
}}

.file-header:hover {{ background: #1c2128; }}

.file-path {{
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 13px;
    color: #58a6ff;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}

.badge {{
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
    white-space: nowrap;
}}

.badge-identical {{ background: #238636; color: #fff; }}
.badge-different {{ background: #9e6a03; color: #fff; }}
.badge-missing {{ background: #da3633; color: #fff; }}
.badge-only-actual {{ background: #1f6feb; color: #fff; }}

.toggle-icon {{ color: #8b949e; font-size: 12px; flex-shrink: 0; }}

.file-content {{ background: #0d1117; }}

.identical-notice {{
    padding: 20px;
    text-align: center;
    color: #3fb950;
    font-size: 13px;
}}

.diff-table-wrapper {{ overflow-x: auto; }}

.diff-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: 12px;
    line-height: 20px;
    table-layout: fixed;
}}

.diff-table td {{ vertical-align: top; }}

.diff-table .line-num {{
    width: 50px;
    min-width: 50px;
    max-width: 50px;
    text-align: right;
    padding: 0 8px;
    color: #484f58;
    background: #0d1117;
    border-right: 1px solid #21262d;
    user-select: none;
    font-size: 11px;
}}

.diff-table .line-content {{
    padding: 0 12px;
    white-space: pre-wrap;
    word-break: break-all;
    width: calc(50% - 50px);
}}

.line-equal {{ background: #0d1117; }}
.line-modified {{ background: rgba(210, 153, 34, 0.15); }}
.line-removed {{ background: rgba(248, 81, 73, 0.15); }}
.line-added {{ background: rgba(63, 185, 80, 0.15); }}
.line-empty {{ background: #161b22; }}

.char-removed {{
    background: rgba(248, 81, 73, 0.4);
    border-radius: 2px;
    padding: 0 1px;
}}

.char-added {{
    background: rgba(63, 185, 80, 0.4);
    border-radius: 2px;
    padding: 0 1px;
}}

.diff-table tr:hover .line-equal {{ background: #161b22; }}

.column-headers {{
    display: flex;
    background: #161b22;
    border-bottom: 1px solid #21262d;
    font-size: 12px;
    font-weight: 600;
    color: #8b949e;
}}

.column-headers .col-label {{
    flex: 1;
    padding: 6px 16px;
    text-align: center;
}}

.column-headers .col-label:first-child {{
    border-right: 1px solid #21262d;
}}

/* 滚动条样式 */
::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: #0d1117; }}
::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: #484f58; }}

/* 响应式 */
@media (max-width: 900px) {{
    .sidebar {{ display: none; }}
}}
</style>
</head>
<body>

<div class="header">
    <h1>{_escape(title)}</h1>
    <div class="meta">{meta_info}</div>
</div>

<div class="stats-bar">
    <div class="stat-item">
        <div class="stat-dot identical"></div>
        <span>Identical:</span>
        <span class="stat-value">{stats['identical']}</span>
    </div>
    <div class="stat-item">
        <div class="stat-dot different"></div>
        <span>Different:</span>
        <span class="stat-value">{stats['different']}</span>
    </div>
    <div class="stat-item">
        <div class="stat-dot missing"></div>
        <span>Missing in actual:</span>
        <span class="stat-value">{stats['missing_in_actual']}</span>
    </div>
    <div class="stat-item">
        <div class="stat-dot only-actual"></div>
        <span>Only in actual (not shown):</span>
        <span class="stat-value">{stats['only_in_actual']}</span>
    </div>
    <div class="stat-item">
        <span>Avg similarity:</span>
        <span class="stat-value">{avg_sim:.4f}</span>
    </div>
    <div class="stat-item">
        <span>Restored files:</span>
        <span class="stat-value">{stats['total']}</span>
    </div>
</div>

<div class="toolbar">
    <button class="filter-btn active" data-filter="all" onclick="filterFiles('all', this)">All</button>
    <button class="filter-btn" data-filter="different" onclick="filterFiles('different', this)">Different</button>
    <button class="filter-btn" data-filter="missing_in_actual" onclick="filterFiles('missing_in_actual', this)">Missing</button>
    <button class="filter-btn" data-filter="identical" onclick="filterFiles('identical', this)">Identical</button>
    <span style="color:#484f58; margin: 0 8px;">|</span>
    <button onclick="expandAll()">Expand All</button>
    <button onclick="collapseAll()">Collapse All</button>
    <div class="search-box">
        <input type="text" id="searchInput" placeholder="Search file name..." oninput="searchFiles(this.value)">
    </div>
</div>

<div class="main-container">
    <div class="sidebar">
        <div class="sidebar-header">Files ({len(file_entries)})</div>
        <div id="fileList">
            {file_list_html}
        </div>
    </div>
    <div class="content-area" id="contentArea">
        {files_content}
    </div>
</div>

<script>
function toggleFile(headerEl) {{
    const block = headerEl.closest('.file-block');
    const content = block.querySelector('.file-content');
    const icon = block.querySelector('.toggle-icon');
    if (content.style.display === 'none') {{
        content.style.display = 'block';
        icon.textContent = '▼';
        block.classList.remove('collapsed');
    }} else {{
        content.style.display = 'none';
        icon.textContent = '▶';
        block.classList.add('collapsed');
    }}
}}

function expandAll() {{
    document.querySelectorAll('.file-block').forEach(block => {{
        const content = block.querySelector('.file-content');
        const icon = block.querySelector('.toggle-icon');
        if (content) {{
            content.style.display = 'block';
            icon.textContent = '▼';
            block.classList.remove('collapsed');
        }}
    }});
}}

function collapseAll() {{
    document.querySelectorAll('.file-block').forEach(block => {{
        const content = block.querySelector('.file-content');
        const icon = block.querySelector('.toggle-icon');
        if (content) {{
            content.style.display = 'none';
            icon.textContent = '▶';
            block.classList.add('collapsed');
        }}
    }});
}}

function filterFiles(status, btnEl) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');

    document.querySelectorAll('.file-block').forEach(block => {{
        if (status === 'all' || block.dataset.status === status) {{
            block.style.display = '';
        }} else {{
            block.style.display = 'none';
        }}
    }});

    document.querySelectorAll('.file-list-item').forEach(item => {{
        if (status === 'all') {{
            item.style.display = '';
        }} else {{
            const cls = 'status-' + status.replace(/_/g, '-');
            item.style.display = item.classList.contains(cls) ? '' : 'none';
        }}
    }});
}}

function searchFiles(query) {{
    query = query.toLowerCase();
    document.querySelectorAll('.file-block').forEach(block => {{
        const path = block.querySelector('.file-path').textContent.toLowerCase();
        block.style.display = path.includes(query) ? '' : 'none';
    }});
    document.querySelectorAll('.file-list-item').forEach(item => {{
        const name = item.querySelector('.file-name').textContent.toLowerCase();
        item.style.display = name.includes(query) ? '' : 'none';
    }});
}}

function scrollToFile(filePath) {{
    const blocks = document.querySelectorAll('.file-block');
    for (const block of blocks) {{
        const path = block.querySelector('.file-path').textContent;
        if (path === filePath) {{
            block.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            // 确保展开
            const content = block.querySelector('.file-content');
            const icon = block.querySelector('.toggle-icon');
            if (content && content.style.display === 'none') {{
                content.style.display = 'block';
                icon.textContent = '▼';
                block.classList.remove('collapsed');
            }}
            // 高亮闪烁
            block.style.outline = '2px solid #58a6ff';
            setTimeout(() => {{ block.style.outline = 'none'; }}, 2000);
            break;
        }}
    }}
}}
</script>
</body>
</html>'''