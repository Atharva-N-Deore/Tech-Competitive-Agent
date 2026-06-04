from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from database import db
from config.settings import BASE_DIR

console = Console()


def generate_daily_report():
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    analyses = db.get_analyses_since(since)

    console.print()
    console.print(Panel(
        f"[bold cyan]Daily Intelligence Briefing[/bold cyan]\n{datetime.now().strftime('%A, %d %B %Y')}",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
    ))

    if not analyses:
        console.print("[yellow]No analyses generated in the past 24 hours.[/yellow]\n")
        return

    report_lines = [
        f"# Daily Intelligence Briefing — {datetime.now().strftime('%Y-%m-%d')}\n",
        f"Generated at: {datetime.now().strftime('%H:%M IST')}\n\n",
    ]

    for analysis in analyses:
        competitor_name = analysis["competitor_name"]
        text = analysis["analysis_text"]
        analyzed_at = analysis.get("analyzed_at", "")

        preview = text[:600] + "..." if len(text) > 600 else text

        console.print(Panel(
            preview,
            title=f"[bold cyan]{competitor_name}[/bold cyan]  [dim]{analyzed_at}[/dim]",
            border_style="blue",
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        console.print()

        report_lines.append(f"## {competitor_name}\n\n{text}\n\n---\n\n")

    report_path = BASE_DIR / "logs" / f"report_{datetime.now().strftime('%Y-%m-%d')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    console.print(f"[green]Report saved to:[/green] {report_path}\n")


def print_signal_summary():
    from config.competitors import COMPETITORS
    table = Table(title="Recent Signals (past 7 days)", box=box.ROUNDED)
    table.add_column("Company", style="cyan")
    table.add_column("Signal Type", style="yellow")
    table.add_column("Count", justify="right")

    for comp in COMPETITORS:
        if not comp.id:
            continue
        signals = db.get_unprocessed_signals(comp.id, days_back=7)
        from collections import Counter
        counts = Counter(s["signal_type"] for s in signals)
        for signal_type, count in sorted(counts.items(), key=lambda x: -x[1]):
            table.add_row(comp.name, signal_type, str(count))

    console.print(table)
