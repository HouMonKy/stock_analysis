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
    (reports_dir / "report_20260519.md").write_text(
        "# 股票分析报告\n\n| 代码 | 建议 |\n| --- | --- |\n| 600519 | 持有 |",
        encoding="utf-8",
    )
    (reports_dir / "market_review_20260519.md").write_text(
        "# 大盘复盘\n\n> 市场缩量震荡。",
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
    assert "reports/report_20260519.html" in index
    assert "reports/market_review_20260519.html" in index
    assert (output_dir / ".nojekyll").exists()
    assert (output_dir / "reports" / "report_20260519.html").exists()
    assert (output_dir / "reports" / "market_review_20260519.html").exists()
    assert "has_reports=true" in github_output.read_text(encoding="utf-8")


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

    assert workflow["permissions"]["pages"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    assert analyze_job["outputs"]["has_reports"] == "${{ steps.report_site.outputs.has_reports }}"
    assert step_by_name["生成 HTML 报告站点"]["id"] == "report_site"
    assert step_by_name["配置 GitHub Pages"]["uses"] == "actions/configure-pages@v6"
    assert step_by_name["上传 Pages 站点"]["uses"] == "actions/upload-pages-artifact@v5"
    assert step_by_name["上传 Pages 站点"]["if"] == "steps.report_site.outputs.has_reports == 'true'"

    deploy_job = workflow["jobs"]["deploy-pages"]
    assert deploy_job["needs"] == "analyze"
    assert deploy_job["if"] == "needs.analyze.outputs.has_reports == 'true'"
    assert deploy_job["steps"][0]["uses"] == "actions/deploy-pages@v5"
