"""Command line. Exactly one JSON line goes to stdout; logs and progress go to stderr."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import NoReturn

from .api import ActionApi, PageviewsApi, SiteMatrixApi, WikidataApi
from .artifacts import ArtifactWriter
from .cache import CacheDatabase, CachedPageviews, JsonStore, PageviewStore, default_cache_path
from .errors import WikitrendsError
from .models import DATA_FLOOR, DateRange
from .output import Payload, error_payload, stdout_payload, to_line
from .replay import FixtureStore, RecordingTransport, ReplayTransport, fixture_dir
from .resolve import EditionRegistry, TopicResolver
from .service import CompareRequest, InterestService, UsageError, parse_titles
from .transport import JsonTransport, WikimediaTransport

log = logging.getLogger("wikitrends")

DEFAULT_WINDOW_DAYS = 730
DATA_LAG_DAYS = 2
SUGGESTED_LIMIT = 20

# Largest editions by pageviews; suggested when the user named no languages.
LARGE_EDITIONS = (
    "en", "ja", "de", "es", "fr", "it", "zh", "pt", "pl", "ar", "fa", "nl", "tr", "uk",
    "id", "sv", "cs", "ko", "vi", "he", "hu", "fi", "ro", "th", "el", "da", "no", "bg", "hi",
)  # fmt: skip


class _Parser(argparse.ArgumentParser):
    """Usage errors become the JSON error line instead of argparse's exit 2."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message, f"Run `{self.prog} --help` for the options.")


@dataclass(frozen=True, slots=True)
class Context:
    service: InterestService
    resolver: TopicResolver
    store: PageviewStore
    writer: ArtifactWriter
    cache_path: Path | None
    today: date
    notices: tuple[str, ...]


def _build(args: argparse.Namespace) -> Context:
    """Composition root: the only place that picks concrete classes."""
    notices: list[str] = []
    today = date.today()
    transport: JsonTransport
    cache_path: Path | None
    if args.offline_fixture:
        replay = ReplayTransport(FixtureStore(fixture_dir(args.offline_fixture)))
        transport, today = replay, replay.today or today
        if replay.synthetic:
            notices.append("Offline fixture: synthetic data, not real Wikipedia traffic.")
        # Fixture data must never leak into the real cache.
        cache_path = Path(args.cache_dir) / "cache.db" if args.cache_dir else None
    else:
        transport = WikimediaTransport()
        if args.record_fixture:
            transport = RecordingTransport(transport, FixtureStore(Path(args.record_fixture)))
        cache_path = Path(args.cache_dir) / "cache.db" if args.cache_dir else default_cache_path()
    db = CacheDatabase(cache_path or ":memory:")
    store = JsonStore(db)
    pages = ActionApi(transport)
    resolver = TopicResolver(
        pages, WikidataApi(transport), EditionRegistry(SiteMatrixApi(transport), store), store
    )
    pageview_store = PageviewStore(db)
    pageviews = CachedPageviews(
        PageviewsApi(transport), pageview_store, refresh=getattr(args, "refresh", False)
    )
    return Context(
        service=InterestService(resolver, pageviews, pages),
        resolver=resolver,
        store=pageview_store,
        writer=ArtifactWriter(Path(getattr(args, "out_dir", "out"))),
        cache_path=cache_path,
        today=today,
        notices=tuple(notices),
    )


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise UsageError(f"bad date {text!r}", "Use YYYY-MM-DD, e.g. 2024-01-01.") from None


def _langs(text: str | None) -> list[str]:
    return [lang.strip().lower() for lang in (text or "").split(",") if lang.strip()]


def _request(args: argparse.Namespace, ctx: Context) -> tuple[CompareRequest, list[str]]:
    notices = list(ctx.notices)
    latest = ctx.today - timedelta(days=1)
    until = _date(args.until) if args.until else ctx.today - timedelta(days=DATA_LAG_DAYS)
    if until > latest:
        notices.append(f"End moved to {latest}: data lag by at least a day.")
        until = latest
    since = _date(args.since) if args.since else until - timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    if since < DATA_FLOOR:
        notices.append(f"Start moved to {DATA_FLOOR}, the first day with pageview data.")
        since = DATA_FLOOR
    if since > until:
        raise UsageError(f"start {since} is after end {until}", "Check --since and --until.")
    titles = parse_titles(args.titles) if args.titles else []
    langs = sorted({a.lang for a in titles}) if titles else sorted(set(_langs(args.langs)))
    request = CompareRequest(
        langs=tuple(langs),
        span=DateRange(since, until),
        topic=args.topic if not titles else None,
        titles=tuple(titles),
        source_lang=(args.source_lang or "en").lower(),
        include_redirects=args.include_redirects,
    )
    return request, notices


def cmd_compare(args: argparse.Namespace, ctx: Context) -> Payload:
    request, notices = _request(args, ctx)
    run = ctx.service.run(request, notices)
    paths = ctx.writer.write(run, args.question or "", with_report=not args.no_report)
    return stdout_payload(run, paths.for_stdout())


def cmd_analyze(args: argparse.Namespace, ctx: Context) -> Payload:
    args.no_report = True
    return cmd_compare(args, ctx)


def cmd_report(args: argparse.Namespace, ctx: Context) -> Payload:
    metrics = ctx.writer.read_metrics(args.from_run)
    request = CompareRequest.from_dict(metrics["request"])
    run = ctx.service.run(request, ctx.notices)
    paths = ctx.writer.write(run, args.question or metrics.get("question", ""), with_report=True)
    return stdout_payload(run, paths.for_stdout())


def cmd_fetch(args: argparse.Namespace, ctx: Context) -> Payload:
    request, notices = _request(args, ctx)
    resolution, views = ctx.service.fetch(request)
    return {
        "ok": True,
        "schema": 1,
        "qid": resolution.qid,
        "languages": [
            {"lang": lang, "title": resolution.articles[lang].title, "days": series.n_observed}
            for lang, series in views.items()
        ],
        "missing": list(resolution.missing),
        "warnings": notices,
    }


def cmd_resolve(args: argparse.Namespace, ctx: Context) -> Payload:
    source = (args.source_lang or "en").lower()
    langs = _langs(args.langs)
    resolution = ctx.resolver.resolve_topic(args.topic, source, langs)
    available = sorted(resolution.articles)
    shown = langs or [lang for lang in LARGE_EDITIONS if lang in resolution.articles]
    shown = shown[:SUGGESTED_LIMIT]
    titles = {
        lang: resolution.articles[lang].title for lang in shown if lang in resolution.articles
    }
    return {
        "ok": True,
        "schema": 1,
        "qid": resolution.qid,
        "source_lang": source,
        "titles": titles,
        "titles_arg": ",".join(f"{lang}:{title}" for lang, title in titles.items()),
        "missing": list(resolution.missing),
        "available_count": len(available),
        "warnings": list(ctx.notices),
    }


def cmd_cache(args: argparse.Namespace, ctx: Context) -> Payload:
    path = ctx.cache_path
    if args.clear:
        if path is not None and path.exists():
            path.unlink()
        return {"ok": True, "schema": 1, "cleared": str(path)}
    series, days = ctx.store.stats()
    return {
        "ok": True,
        "schema": 1,
        "path": str(path) if path else ":memory:",
        "size_bytes": path.stat().st_size if path and path.exists() else 0,
        "series": series,
        "days": days,
    }


Handler = Callable[[argparse.Namespace, Context], Payload]


def _request_options(parser: argparse.ArgumentParser, topic_required: bool = False) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--topic", help="topic in the source language, e.g. 'Astronomy'")
    if not topic_required:
        source.add_argument("--titles", help="exact titles, e.g. uk:Астрономія,pl:Astronomia")
    parser.add_argument("--langs", help="comma-separated edition codes, e.g. uk,pl,cs")
    parser.add_argument("--since", help="first day, YYYY-MM-DD (default: two years back)")
    parser.add_argument("--until", help="last day, YYYY-MM-DD (default: two days ago)")
    parser.add_argument("--source-lang", help="edition to search the topic in (default: en)")
    parser.add_argument(
        "--include-redirects", action="store_true", help="also sum views of redirects"
    )
    parser.add_argument("--refresh", action="store_true", help="ignore cached pageviews")


def build_parser() -> argparse.ArgumentParser:
    common = _Parser(add_help=False)
    common.add_argument("--cache-dir", help="cache directory (default ~/.cache/wikipedia-interest)")
    common.add_argument("--offline-fixture", help="replay a recorded fixture: 'demo' or a path")
    common.add_argument("--record-fixture", help="record every response into this directory")
    common.add_argument("-v", "--verbose", action="store_true", help="log progress to stderr")
    output = _Parser(add_help=False)
    output.add_argument("--out-dir", default="out", help="artifact root (default ./out)")
    output.add_argument("--question", help="the user's question, printed on the report")

    parser = _Parser(prog="wikitrends", description="Wikipedia pageview interest analysis.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def add(name: str, handler: Handler, help_text: str, *parents: _Parser) -> _Parser:
        sub = commands.add_parser(name, parents=[common, *parents], help=help_text)
        sub.set_defaults(handler=handler)
        return sub

    compare = add("compare", cmd_compare, "resolve, fetch, analyze, chart and report", output)
    _request_options(compare)
    compare.add_argument("--no-report", action="store_true", help="skip charts and the PDF")
    _request_options(add("analyze", cmd_analyze, "statistics only, no charts", output))
    _request_options(add("fetch", cmd_fetch, "only download into the cache"))
    report = add("report", cmd_report, "rebuild charts and PDF of an earlier run", output)
    report.add_argument("--from-run", required=True, help="slug printed by compare/analyze")
    resolve = add("resolve", cmd_resolve, "topic to canonical titles per language")
    resolve.add_argument("--topic", required=True)
    resolve.add_argument("--langs", help="only these editions")
    resolve.add_argument("--source-lang", help="edition to search in (default: en)")
    cache = add("cache", cmd_cache, "cache status or --clear")
    cache.add_argument("--status", action="store_true", help="default action")
    cache.add_argument("--clear", action="store_true", help="delete the cache file")
    return parser


def run(argv: Sequence[str] | None = None) -> tuple[Payload, int]:
    """Runs one command; returns the payload and the exit code."""
    try:
        args = build_parser().parse_args(argv)
        logging.basicConfig(
            stream=sys.stderr,
            level=logging.INFO if args.verbose else logging.WARNING,
            format="wikitrends: %(message)s",
        )
        handler: Handler = args.handler
        return handler(args, _build(args)), 0
    except WikitrendsError as exc:
        return error_payload(exc), 1
    except Exception as exc:  # The contract holds even for bugs: one JSON line, exit 1.
        log.exception("unexpected error")
        internal = WikitrendsError(
            f"internal error: {exc}", "Rerun with -v and report the traceback from stderr."
        )
        return error_payload(internal), 1


def main(argv: Sequence[str] | None = None) -> int:
    stdout = sys.stdout
    # Anything a library prints must not break the one-line stdout contract.
    with contextlib.redirect_stdout(sys.stderr):
        payload, code = run(argv)
    print(to_line(payload), file=stdout)
    return code
