# -*- coding: utf-8 -*-
"""Tests for the static report site builder."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

build_report_site = importlib.import_module("build_report_site")


def test_build_report_site_creates_index_and_report_pages(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20260519_20260519-183000_run-1_attempt-1.md").write_text(
        "# 🎯 2026-05-19 决策仪表盘\n\n## 📊 汇总\n\n🎯 **贵州茅台(600519)**: 持有 | 评分 72",
        encoding="utf-8",
    )
    (reports_dir / "market_review_20260519.md").write_text(
        "# 大盘复盘\n\n# A股大盘复盘\n\n> 市场缩量震荡。",
        encoding="utf-8",
    )

    output_dir = tmp_path / "site"
    github_output = tmp_path / "github_output.txt"
    summary = build_report_site.build_report_site(
        reports_dir=reports_dir,
        output_dir=output_dir,
        github_output=github_output,
        now=datetime(2026, 5, 19, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert summary.has_reports is True
    assert summary.report_count == 2
    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "最新股票分析报告" in index
    assert "最新大盘分析报告" in index
    assert "贵州茅台(600519) - 2026-05-19 18:30" in index
    assert "A股大盘复盘 - 2026-05-19" in index
    assert "reports/report_20260519_20260519-183000_run-1_attempt-1.html" in index
    assert "reports/market_review_20260519.html" in index
    assert (output_dir / ".nojekyll").exists()
    assert (output_dir / "reports" / "report_20260519_20260519-183000_run-1_attempt-1.html").exists()
    assert (output_dir / "reports" / "market_review_20260519.html").exists()
    assert "has_reports=true" in github_output.read_text(encoding="utf-8")


def test_build_report_site_names_multi_stock_reports_from_stock_labels(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20260520_20260520-235602_run-2_attempt-1.md").write_text(
        "# 🎯 2026-05-20 决策仪表盘\n\n"
        "🎯 **中科曙光(603019)**: 持有 | 评分 68\n"
        "🟡 **贵州茅台(600519)**: 观望 | 评分 60\n"
        "🔴 **宁德时代(300750)**: 减仓 | 评分 42\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "site"
    build_report_site.build_report_site(reports_dir=reports_dir, output_dir=output_dir)

    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "中科曙光(603019)、贵州茅台(600519)、宁德时代(300750) - 2026-05-20 23:56" in index


def test_build_report_site_names_market_reports_from_scope_and_timestamp(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "market_review_20260520_hk_us_20260520-235602_run-2_attempt-1.md").write_text(
        "# 🎯 大盘复盘\n\n# 港股大盘复盘\n\n复盘正文\n\n---\n\n# 美股大盘复盘\n\n复盘正文",
        encoding="utf-8",
    )

    output_dir = tmp_path / "site"
    build_report_site.build_report_site(reports_dir=reports_dir, output_dir=output_dir)

    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "港股、美股大盘复盘 - 2026-05-20 23:56" in index


def test_daily_analysis_archives_market_report_with_region_in_filename() -> None:
    workflow = yaml.safe_load((ROOT_DIR / ".github/workflows/daily_analysis.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    archive_step = next(step for step in steps if step.get("id") == "report_archive")

    assert "MARKET_REVIEW_REGION" in archive_step["run"]
    assert "market_review_*" in archive_step["run"]


def test_build_report_site_escapes_raw_html(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20260519.md").write_text(
        "# 安全检查\n\n<script>alert('xss')</script>",
        encoding="utf-8",
    )

    output_dir = tmp_path / "site"
    build_report_site.build_report_site(reports_dir=reports_dir, output_dir=output_dir)

    report_html = (output_dir / "reports" / "report_20260519.html").read_text(encoding="utf-8")
    assert "<script>alert" not in report_html
    assert "&lt;script&gt;" in report_html


def test_build_report_site_reports_empty_state(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "site"
    github_output = tmp_path / "github_output.txt"

    summary = build_report_site.build_report_site(
        reports_dir=reports_dir,
        output_dir=output_dir,
        github_output=github_output,
    )

    assert summary.has_reports is False
    assert summary.report_count == 0
    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "还没有可展示的 Markdown 报告" in index
    assert "has_reports=false" in github_output.read_text(encoding="utf-8")


def test_daily_analysis_workflow_publishes_pages_when_reports_exist() -> None:
    workflow = yaml.safe_load((ROOT_DIR / ".github/workflows/daily_analysis.yml").read_text(encoding="utf-8"))
    analyze_job = workflow["jobs"]["analyze"]
    steps = analyze_job["steps"]
    step_by_name = {step.get("name"): step for step in steps}

    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["pages"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    assert analyze_job["outputs"]["has_reports"] == "${{ steps.report_site.outputs.has_reports }}"
    assert "report-archive" in step_by_name["恢复持久历史报告归档"]["run"]
    assert step_by_name["合并本次报告到历史归档"]["id"] == "report_archive"
    assert "--reports-dir reports-archive" in step_by_name["生成 HTML 报告站点"]["run"]
    assert step_by_name["生成 HTML 报告站点"]["id"] == "report_site"
    assert "git push origin report-archive" in step_by_name["保存历史报告到持久分支"]["run"]
    assert step_by_name["配置 GitHub Pages"]["uses"] == "actions/configure-pages@v6"
    assert step_by_name["上传 Pages 站点"]["uses"] == "actions/upload-pages-artifact@v5"
    assert step_by_name["上传 Pages 站点"]["if"] == "steps.report_site.outputs.has_reports == 'true'"

    deploy_job = workflow["jobs"]["deploy-pages"]
    assert deploy_job["needs"] == "analyze"
    assert deploy_job["if"] == "needs.analyze.outputs.has_reports == 'true'"
    assert deploy_job["steps"][0]["uses"] == "actions/deploy-pages@v5"
