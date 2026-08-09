#!/usr/bin/env python3
"""Command line for doc-formatter.

    format-doc format    --input thesis.docx --rules guide.pdf --out out.docx
    format-doc format    --input thesis.docx --rules-id ameu --out out.docx
    format-doc extract   guide.pdf --save-as "AMEU — Dance Academy"
    format-doc library   list | show <id> | copy <id> | delete <id> | import <file>
    format-doc structure thesis.docx --rules-id <id>
    format-doc mate      ping

UI strings follow --lang; this help text is English only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from docformat import __version__, i18n
from docformat.extract.mate_client import MateClient, MateConfig
from docformat.extract.pipeline import extract_rule_set
from docformat.extract.source import NoTextLayerError, read_rules_document
from docformat.formatting.engine import FormatOptions, format_document
from docformat.library import RuleLibrary
from docformat.rules import RuleSet, dump_rule_set, load_rule_set

PRESETS_DIR = Path(__file__).resolve().parent / "presets"


def _client_or_none(offline: bool) -> MateClient | None:
    if offline:
        return None
    config = MateConfig.from_env()
    if not config.is_configured:
        print(
            "! MATE_PAT is not set — falling back to the regex heuristic.\n"
            "  For agent extraction set MATE_PAT (and MATE_BASE_URL if needed).",
            file=sys.stderr,
        )
        return None
    return MateClient(config)


def _iter_presets():
    """Preseti iz `presets/`, preskačući fajlove koji nisu setovi pravila."""
    for path in sorted(PRESETS_DIR.glob("*.json")):
        try:
            yield path, load_rule_set(path)
        except Exception:
            continue


def _find_preset(identifier: str) -> RuleSet | None:
    """Preset po imenu fajla ili po `meta.id` unutar njega."""
    for path, candidate in _iter_presets():
        if path.stem == identifier or candidate.meta.id == identifier:
            return candidate
    return None


def _resolve_rules(args, library: RuleLibrary) -> RuleSet:
    """Set pravila iz jednog od tri izvora, redom po eksplicitnosti."""
    if getattr(args, "rules_json", None):
        return load_rule_set(args.rules_json)

    if getattr(args, "rules_id", None):
        if library.exists(args.rules_id):
            return library.load(args.rules_id)
        preset = _find_preset(args.rules_id)
        if preset is not None:
            return preset
        available = ", ".join(sorted(p.stem for p in PRESETS_DIR.glob("*.json")))
        raise SystemExit(
            f"Rule set '{args.rules_id}' was not found in the library or in presets/. "
            f"Available presets: {available or '—'}"
        )

    if getattr(args, "rules", None):
        outcome = _extract(Path(args.rules), library, offline=args.offline)
        return outcome.rule_set

    raise SystemExit("Give a rule source: --rules, --rules-id or --rules-json.")


def _extract(path: Path, library: RuleLibrary, offline: bool):
    try:
        document = read_rules_document(path)
    except NoTextLayerError as exc:
        raise SystemExit(str(exc)) from exc

    outcome = extract_rule_set(
        document,
        client=_client_or_none(offline),
        library=library,
        on_progress=lambda msg: print(f"  {msg}", file=sys.stderr),
    )
    for warning in outcome.warnings:
        print(f"! {warning}", file=sys.stderr)
    print(f"  Rule source: {outcome.source}", file=sys.stderr)
    return outcome


# --------------------------------------------------------------------------
# Komande
# --------------------------------------------------------------------------


def cmd_format(args) -> int:
    library = RuleLibrary(args.library_dir)
    rule_set = _resolve_rules(args, library)

    options = FormatOptions(
        dry_run=args.dry_run,
        strict_structure=not args.lenient,
        clean_empty_paragraphs=not args.no_cleanup,
        insert_toc=args.toc,
    )
    result = format_document(args.input, rule_set, options)

    print(f"Rules: {rule_set.meta.display_name} ({rule_set.meta.id})")
    print(result.report.to_text())

    if args.dry_run:
        print("\nDry run — nothing was written.")
        return 0

    output = result.save(args.out)
    print(f"\nWritten: {output}")

    if args.save_rules:
        saved = library.save(rule_set)
        print(f"Rules saved to the library: {saved.meta.id}")
    return 0


def cmd_extract(args) -> int:
    library = RuleLibrary(args.library_dir)
    outcome = _extract(Path(args.guide), library, offline=args.offline)
    rule_set = outcome.rule_set

    if args.save_as:
        rule_set.meta.display_name = args.save_as
        rule_set.meta.id = library.unique_id(args.save_as)

    matches = library.find_matches(rule_set.meta.institution)
    if matches and matches[0].is_strong:
        print(
            f"! The library already holds a similar set: "
            f"{matches[0].rule_set.meta.display_name} ({matches[0].score})",
            file=sys.stderr,
        )

    if args.out:
        dump_rule_set(rule_set, args.out)
        print(f"Written: {args.out}")
    if args.save_as or args.save:
        saved = library.save(rule_set)
        print(f"Saved to the library: {saved.meta.id}")
    if not args.out and not (args.save_as or args.save):
        print(rule_set.model_dump_json(indent=2))

    if rule_set.unresolved:
        print(
            f"\nUnresolved ({len(rule_set.unresolved)}): {', '.join(rule_set.unresolved)}",
            file=sys.stderr,
        )
    return 0


def cmd_library(args) -> int:
    library = RuleLibrary(args.library_dir)

    if args.action == "list":
        sets = library.list()
        if not sets:
            print("The library is empty.")
            return 0
        for rule_set in sets:
            institution = rule_set.meta.institution
            where = " / ".join(p for p in (institution.university, institution.faculty) if p)
            print(f"{rule_set.meta.id:44} {rule_set.meta.display_name}")
            print(f"{'':44} {where or '—'}  [{rule_set.meta.origin}]")
        return 0

    if args.action == "show":
        print(library.load(args.target).model_dump_json(indent=2))
        return 0

    if args.action == "copy":
        copy = library.duplicate(args.target)
        print(f"Copied: {copy.meta.id}")
        return 0

    if args.action == "delete":
        library.delete(args.target)
        print(f"Deleted: {args.target}")
        return 0

    if args.action == "import":
        imported = library.import_(args.target)
        print(f"Imported: {imported.meta.id}")
        return 0

    if args.action == "export":
        rule_set = library.load(args.target)
        destination = Path(args.out or f"{rule_set.meta.id}.json")
        dump_rule_set(rule_set, destination)
        print(f"Exported: {destination}")
        return 0

    raise SystemExit(f"Unknown action: {args.action}")


def cmd_structure(args) -> int:
    library = RuleLibrary(args.library_dir)
    rule_set = _resolve_rules(args, library)

    from docformat.formatting.engine import describe_structure

    counts = describe_structure(args.input, rule_set)
    for key in sorted(counts):
        print(f"  {key:40} {counts[key]}")
    return 0


def cmd_mate(args) -> int:
    config = MateConfig.from_env()
    print(f"URL   : {config.base_url}")
    print(f"Agent : {config.agent}")
    print(f"Token : {'set' if config.is_configured else 'NOT set (MATE_PAT)'}")
    ok, message = MateClient(config).ping()
    print(f"Status: {'OK' if ok else 'ERROR'} — {message}")
    return 0 if ok else 1


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="format-doc", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--library-dir", default=None, help="rule library directory")
    parser.add_argument(
        "--lang",
        default=None,
        choices=list(i18n.available_languages()),
        help="language for messages (default: DOC_FORMATTER_LANG, else en)",
    )
    parser.add_argument("--offline", action="store_true", help="skip the LLM, use the heuristic")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_rule_source(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--rules", help="style guide (.pdf or .docx) to extract rules from")
        group.add_argument("--rules-id", help="set id from the library or presets/")
        group.add_argument("--rules-json", help="path to a rules JSON file")

    p_format = sub.add_parser("format", help="format a .docx against a rule set")
    p_format.add_argument("--input", required=True)
    p_format.add_argument("--out", default="formatiran.docx")
    add_rule_source(p_format)
    p_format.add_argument("--dry-run", action="store_true", help="show deletions without writing")
    p_format.add_argument("--no-cleanup", action="store_true", help="keep empty paragraphs")
    p_format.add_argument("--lenient", action="store_true",
                          help="continue even if the structure is not recognised")
    p_format.add_argument("--toc", action=argparse.BooleanOptionalAction, default=None,
                          help="insert a Word TOC field (default: as the rules say)")
    p_format.add_argument("--save-rules", action="store_true", help="save the rules to the library")
    p_format.set_defaults(func=cmd_format)

    p_extract = sub.add_parser("extract", help="extract rules from a style guide")
    p_extract.add_argument("guide")
    p_extract.add_argument("--out", help="write the rules JSON to a file")
    p_extract.add_argument("--save", action="store_true", help="save to the library")
    p_extract.add_argument("--save-as", help="save to the library under this name")
    p_extract.set_defaults(func=cmd_extract)

    p_library = sub.add_parser("library", help="manage the rule library")
    p_library.add_argument("action", choices=["list", "show", "copy", "delete", "import", "export"])
    p_library.add_argument("target", nargs="?")
    p_library.add_argument("--out")
    p_library.set_defaults(func=cmd_library)

    p_structure = sub.add_parser("structure", help="structure detection diagnostics")
    p_structure.add_argument("input")
    add_rule_source(p_structure)
    p_structure.set_defaults(func=cmd_structure)

    p_mate = sub.add_parser("mate", help="check the LLM agent connection")
    p_mate.add_argument("action", nargs="?", default="ping", choices=["ping"])
    p_mate.set_defaults(func=cmd_mate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    i18n.set_language(args.lang or os.getenv("DOC_FORMATTER_LANG", i18n.DEFAULT_LANGUAGE))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
