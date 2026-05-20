# -*- coding: utf-8 -*-
"""Build a static GitHub Pages site from generated Markdown reports."""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo


REPORT_DATE_RE = re.compile(r"(?P<date>\d{8})")
REPORT_TIMESTAMP_RE = re.compile(r"(?P<stamp>\d{8}-\d{6})")
STOCK_LABEL_RE = re.compile(
    r"\*\*(?P<name>[^*\n()（）]{1,80})\s*[(（](?P<code>[A-Za-z0-9._-]{2,20})[)）]\*\*"
)
MARKET_SCOPE_PATTERNS = (
    ("A股", ("A股", "A 股", "A-share", "A Share", "cn")),
    ("港股", ("港股", "HK Market", "Hong Kong", "hk")),
    ("美股", ("美股", "US Market", "U.S. Market", "us")),
)
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
MARKDOWN_EXTRAS = ["tables", "fenced-code-blocks", "break-on-newline", "cuddled-lists"]


@dataclass(frozen=True)
class ReportPage:
    source_path: Path
    output_name: str
    title: str
    kind: str
    kind_label: str
    report_date: str
    updated_at: datetime


@dataclass(frozen=True)
class BuildSummary:
    has_reports: bool
    report_count: int
    output_dir: Path
    index_path: Path


def _load_markdown2():
    try:
        import markdown2  # type: ignore
    except ModuleNotFoundError:
        return None
    return markdown2


def _markdown_to_html(markdown_text: str) -> str:
    markdown2 = _load_markdown2()
    if markdown2 is None:
        return f"<pre>{html.escape(markdown_text)}</pre>"
    try:
        return markdown2.markdown(
            markdown_text,
            extras=MARKDOWN_EXTRAS,
            safe_mode="escape",
        )
    except TypeError:
        return markdown2.markdown(
            html.escape(markdown_text),
            extras=MARKDOWN_EXTRAS,
        )


def _safe_output_name(path: Path) -> str:
    stem = SAFE_FILENAME_RE.sub("-", path.stem).strip(".-") or "report"
    return f"{stem}.html"


def _format_report_date(path: Path) -> str:
    match = REPORT_DATE_RE.search(path.stem)
    if not match:
        return "未知日期"
    raw = match.group("date")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _format_report_timestamp(path: Path) -> Optional[str]:
    match = REPORT_TIMESTAMP_RE.search(path.stem)
    if not match:
        return None
    raw = match.group("stamp")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} {raw[9:11]}:{raw[11:13]}"


def _extract_stock_labels(markdown_text: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for match in STOCK_LABEL_RE.finditer(markdown_text):
        name = re.sub(r"\s+", " ", match.group("name")).strip()
        code = match.group("code").strip()
        if not name or not code:
            continue
        label = f"{name}({code})"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def _stock_title_from_labels(path: Path, stock_labels: list[str]) -> Optional[str]:
    if not stock_labels:
        return None

    date_label = _format_report_timestamp(path) or _format_report_date(path)
    if len(stock_labels) == 1:
        return f"{stock_labels[0]} - {date_label}"
    if len(stock_labels) <= 3:
        return f"{'、'.join(stock_labels)} - {date_label}"
    return f"{'、'.join(stock_labels[:2])} 等 {len(stock_labels)} 只股票 - {date_label}"


def _extract_market_scopes(path: Path, markdown_text: str) -> list[str]:
    haystack = f"{path.stem}\n{markdown_text}"
    scopes: list[str] = []
    for label, patterns in MARKET_SCOPE_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            scopes.append(label)
    return scopes


def _market_title(path: Path, markdown_text: str) -> str:
    date_label = _format_report_timestamp(path) or _format_report_date(path)
    scopes = _extract_market_scopes(path, markdown_text)
    if scopes:
        return f"{'、'.join(scopes)}大盘复盘 - {date_label}"
    return f"大盘复盘 - {date_label}"


def _first_heading(markdown_text: str) -> Optional[str]:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def _kind_for_report(path: Path) -> tuple[str, str]:
    if path.stem.startswith("market_review"):
        return "market", "大盘分析报告"
    return "stock", "股票分析报告"


def _page_title(path: Path, markdown_text: str) -> str:
    kind, _ = _kind_for_report(path)
    if kind == "stock":
        stock_title = _stock_title_from_labels(path, _extract_stock_labels(markdown_text))
        if stock_title:
            return stock_title
    elif kind == "market":
        return _market_title(path, markdown_text)

    heading = _first_heading(markdown_text)
    if heading:
        return heading
    date_label = _format_report_date(path)
    if kind == "market":
        return f"{date_label} 大盘分析报告"
    return f"{date_label} 股票分析报告"


def _discover_reports(reports_dir: Path) -> list[Path]:
    if not reports_dir.exists():
        return []
    return sorted(
        (path for path in reports_dir.glob("*.md") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def _clean_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)


def _html_document(title: str, body: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --surface: #ffffff;
      --surface-soft: #f1f5f9;
      --text: #172033;
      --muted: #64748b;
      --line: #d8dee9;
      --brand: #0f766e;
      --brand-strong: #115e59;
      --accent: #b45309;
      --danger: #b91c1c;
      --shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, rgba(15, 118, 110, 0.08), rgba(15, 118, 110, 0) 320px),
        var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.66;
    }}
    a {{ color: var(--brand-strong); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 56px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .mark {{
      width: 38px;
      height: 38px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--brand);
      color: #fff;
      font-weight: 800;
      letter-spacing: 0;
    }}
    .brand-title {{
      margin: 0;
      font-size: clamp(22px, 3vw, 34px);
      line-height: 1.16;
      letter-spacing: 0;
    }}
    .brand-meta {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .pill {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.74);
      color: var(--muted);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 18px;
    }}
    .card h2 {{
      margin: 0 0 8px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    .card p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .report-list {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .report-item {{
      display: grid;
      grid-template-columns: 112px 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }}
    .tag {{
      width: fit-content;
      border-radius: 999px;
      padding: 4px 8px;
      background: var(--surface-soft);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .report-title {{
      font-weight: 700;
      color: var(--text);
      overflow-wrap: anywhere;
    }}
    .report-date {{
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .empty {{
      padding: 28px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
    }}
    .report-frame {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: clamp(18px, 4vw, 36px);
    }}
    .report-frame h1, .report-frame h2 {{
      line-height: 1.25;
      letter-spacing: 0;
      border-bottom: 1px solid var(--line);
      padding-bottom: 0.32em;
    }}
    .report-frame h1 {{ font-size: clamp(24px, 4vw, 36px); color: var(--brand-strong); }}
    .report-frame h2 {{ font-size: clamp(20px, 3vw, 26px); margin-top: 1.4em; }}
    .report-frame h3 {{ font-size: 18px; margin-top: 1.2em; }}
    .report-frame table {{
      width: 100%;
      border-collapse: collapse;
      display: block;
      overflow-x: auto;
      margin: 16px 0;
      font-size: 14px;
    }}
    .report-frame th, .report-frame td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    .report-frame th {{ background: var(--surface-soft); }}
    .report-frame blockquote {{
      margin: 14px 0;
      padding: 2px 16px;
      border-left: 4px solid var(--brand);
      background: rgba(15, 118, 110, 0.07);
      color: #334155;
    }}
    .report-frame code {{
      border-radius: 4px;
      padding: 0.15em 0.35em;
      background: #e5e7eb;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    .report-frame pre {{
      overflow-x: auto;
      padding: 14px;
      border-radius: 8px;
      background: #111827;
      color: #f8fafc;
    }}
    .report-frame hr {{
      border: 0;
      border-top: 1px solid var(--line);
      margin: 24px 0;
    }}
    .backlink {{
      display: inline-flex;
      align-items: center;
      margin-bottom: 16px;
      color: var(--brand-strong);
      font-weight: 700;
    }}
    @media (max-width: 720px) {{
      .shell {{ width: min(100% - 24px, 1120px); padding-top: 20px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .report-item {{ grid-template-columns: 1fr; }}
      .report-date {{ white-space: normal; }}
    }}
  </style>
</head>
<body>
  {body}
</body>
</html>
"""


def _render_index(site_title: str, pages: list[ReportPage], generated_at: datetime) -> str:
    latest_stock = next((page for page in pages if page.kind == "stock"), None)
    latest_market = next((page for page in pages if page.kind == "market"), None)
    cards = [
        _latest_card("最新股票分析报告", latest_stock),
        _latest_card("最新大盘分析报告", latest_market),
    ]
    report_items = "\n".join(_report_item(page) for page in pages)
    if not report_items:
        report_items = '<div class="empty">还没有可展示的 Markdown 报告。本次 workflow 未生成报告时，会跳过 Pages 发布。</div>'

    body = f"""
  <main class="shell">
    <section class="topbar">
      <div class="brand">
        <div class="mark">DSA</div>
        <div>
          <h1 class="brand-title">{html.escape(site_title)}</h1>
          <p class="brand-meta">生成时间：{html.escape(_format_datetime(generated_at))}</p>
        </div>
      </div>
      <div class="pill">GitHub Pages 自动发布</div>
    </section>
    <section class="grid">
      {"".join(cards)}
    </section>
    <section class="card">
      <h2>全部报告</h2>
      <p>按生成时间倒序展示，包含个股决策仪表盘和大盘复盘。</p>
      <div class="report-list">
        {report_items}
      </div>
    </section>
  </main>
"""
    return _html_document(site_title, body)


def _latest_card(title: str, page: Optional[ReportPage]) -> str:
    if page is None:
        return f"""
      <article class="card">
        <h2>{html.escape(title)}</h2>
        <p>本次运行未生成对应报告。</p>
      </article>
"""
    href = f"reports/{html.escape(page.output_name)}"
    return f"""
      <article class="card">
        <h2><a href="{href}">{html.escape(title)}</a></h2>
        <p>{html.escape(page.report_date)} · {html.escape(page.title)}</p>
      </article>
"""


def _report_item(page: ReportPage) -> str:
    href = f"reports/{html.escape(page.output_name)}"
    return f"""
        <a class="report-item" href="{href}">
          <span class="tag">{html.escape(page.kind_label)}</span>
          <span class="report-title">{html.escape(page.title)}</span>
          <span class="report-date">{html.escape(page.report_date)}</span>
        </a>
"""


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _render_report_page(site_title: str, page: ReportPage, markdown_text: str) -> str:
    content = _markdown_to_html(markdown_text)
    body = f"""
  <main class="shell">
    <a class="backlink" href="../index.html">返回报告首页</a>
    <article class="report-frame">
      {content}
    </article>
  </main>
"""
    return _html_document(f"{page.title} - {site_title}", body)


def _write_github_output(path: Optional[Path], pairs: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def _build_pages(report_paths: Iterable[Path], output_dir: Path, site_title: str) -> list[ReportPage]:
    pages: list[ReportPage] = []
    used_names: set[str] = set()
    reports_output_dir = output_dir / "reports"

    for path in report_paths:
        markdown_text = path.read_text(encoding="utf-8")
        output_name = _safe_output_name(path)
        if output_name in used_names:
            output_name = f"{_safe_output_name(path)[:-5]}-{len(used_names) + 1}.html"
        used_names.add(output_name)

        kind, kind_label = _kind_for_report(path)
        page = ReportPage(
            source_path=path,
            output_name=output_name,
            title=_page_title(path, markdown_text),
            kind=kind,
            kind_label=kind_label,
            report_date=_format_report_date(path),
            updated_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
        )
        pages.append(page)
        (reports_output_dir / output_name).write_text(
            _render_report_page(site_title, page, markdown_text),
            encoding="utf-8",
        )

    return pages


def build_report_site(
    reports_dir: Path,
    output_dir: Path,
    site_title: str = "每日股票分析报告",
    timezone_name: str = "Asia/Shanghai",
    github_output: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> BuildSummary:
    """Create a static HTML site from Markdown reports."""

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")

    generated_at = (now or datetime.now(tz)).astimezone(tz)
    report_paths = _discover_reports(reports_dir)

    _clean_output_dir(output_dir)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    pages = _build_pages(report_paths, output_dir, site_title)
    index_path = output_dir / "index.html"
    index_path.write_text(_render_index(site_title, pages, generated_at), encoding="utf-8")

    summary = BuildSummary(
        has_reports=bool(pages),
        report_count=len(pages),
        output_dir=output_dir,
        index_path=index_path,
    )
    _write_github_output(
        github_output,
        {
            "has_reports": "true" if summary.has_reports else "false",
            "report_count": str(summary.report_count),
            "site_dir": str(output_dir),
        },
    )
    return summary


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static HTML pages for generated stock reports.")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing Markdown report files.")
    parser.add_argument("--output-dir", default="reports-site", help="Directory to write the generated site.")
    parser.add_argument("--site-title", default="每日股票分析报告", help="Title shown on the report index.")
    parser.add_argument("--timezone", default=os.getenv("REPORT_SITE_TIMEZONE", "Asia/Shanghai"))
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"))
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    summary = build_report_site(
        reports_dir=Path(args.reports_dir),
        output_dir=Path(args.output_dir),
        site_title=args.site_title,
        timezone_name=args.timezone,
        github_output=Path(args.github_output) if args.github_output else None,
    )
    if summary.has_reports:
        print(f"Built report site with {summary.report_count} report(s): {summary.index_path}")
    else:
        print(f"No Markdown reports found in {args.reports_dir}; generated placeholder index only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
