#!/usr/bin/env python3
"""Komandna linija za doc_formater.

    format-doc format   --input rad.docx --rules pravilnik.pdf --out out.docx
    format-doc format   --input rad.docx --rules-id ameu-akademija-za-ples --out out.docx
    format-doc extract  pravilnik.pdf --save-as "AMEU — Akademija za ples"
    format-doc library  list | show <id> | copy <id> | delete <id> | import <fajl>
    format-doc structure rad.docx --rules-id <id>
    format-doc mate     ping
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
            "! MATE_PAT nije postavljen — koristi se regex heuristika.\n"
            "  Za ekstrakciju preko agenta postavi MATE_PAT (i po potrebi MATE_BASE_URL).",
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
            f"Set pravila '{args.rules_id}' nije nađen ni u biblioteci ni u presets/. "
            f"Dostupni preseti: {available or '—'}"
        )

    if getattr(args, "rules", None):
        outcome = _extract(Path(args.rules), library, offline=args.offline)
        return outcome.rule_set

    raise SystemExit("Navedi izvor pravila: --rules, --rules-id ili --rules-json.")


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
    print(f"  Izvor pravila: {outcome.source}", file=sys.stderr)
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

    print(f"Pravila: {rule_set.meta.display_name} ({rule_set.meta.id})")
    print(result.report.to_text())

    if args.dry_run:
        print("\nProbni prolaz — ništa nije upisano.")
        return 0

    output = result.save(args.out)
    print(f"\nZapisano: {output}")

    if args.save_rules:
        saved = library.save(rule_set)
        print(f"Pravila sačuvana u biblioteku: {saved.meta.id}")
    return 0


def cmd_extract(args) -> int:
    library = RuleLibrary(args.library_dir)
    outcome = _extract(Path(args.pravilnik), library, offline=args.offline)
    rule_set = outcome.rule_set

    if args.save_as:
        rule_set.meta.display_name = args.save_as
        rule_set.meta.id = library.unique_id(args.save_as)

    matches = library.find_matches(rule_set.meta.institution)
    if matches and matches[0].is_strong:
        print(
            f"! U biblioteci već postoji sličan set: "
            f"{matches[0].rule_set.meta.display_name} ({matches[0].score})",
            file=sys.stderr,
        )

    if args.out:
        dump_rule_set(rule_set, args.out)
        print(f"Zapisano: {args.out}")
    if args.save_as or args.save:
        saved = library.save(rule_set)
        print(f"Sačuvano u biblioteku: {saved.meta.id}")
    if not args.out and not (args.save_as or args.save):
        print(rule_set.model_dump_json(indent=2))

    if rule_set.unresolved:
        print(
            f"\nNerešeno ({len(rule_set.unresolved)}): {', '.join(rule_set.unresolved)}",
            file=sys.stderr,
        )
    return 0


def cmd_library(args) -> int:
    library = RuleLibrary(args.library_dir)

    if args.action == "list":
        sets = library.list()
        if not sets:
            print("Biblioteka je prazna.")
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
        print(f"Kopirano: {copy.meta.id}")
        return 0

    if args.action == "delete":
        library.delete(args.target)
        print(f"Obrisano: {args.target}")
        return 0

    if args.action == "import":
        imported = library.import_(args.target)
        print(f"Uvezeno: {imported.meta.id}")
        return 0

    if args.action == "export":
        rule_set = library.load(args.target)
        destination = Path(args.out or f"{rule_set.meta.id}.json")
        dump_rule_set(rule_set, destination)
        print(f"Izvezeno: {destination}")
        return 0

    raise SystemExit(f"Nepoznata akcija: {args.action}")


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
    print(f"Token : {'postavljen' if config.is_configured else 'NIJE postavljen (MATE_PAT)'}")
    ok, message = MateClient(config).ping()
    print(f"Status: {'OK' if ok else 'GREŠKA'} — {message}")
    return 0 if ok else 1


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="format-doc", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library-dir", default=None, help="direktorijum biblioteke pravila")
    parser.add_argument("--offline", action="store_true", help="ne zovi Mate, koristi heuristiku")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_rule_source(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--rules", help="pravilnik (.pdf ili .docx) iz kog se izvlače pravila")
        group.add_argument("--rules-id", help="id seta iz biblioteke ili presets/")
        group.add_argument("--rules-json", help="putanja do rules JSON fajla")

    p_format = sub.add_parser("format", help="formatira .docx po pravilima")
    p_format.add_argument("--input", required=True)
    p_format.add_argument("--out", default="formatiran.docx")
    add_rule_source(p_format)
    p_format.add_argument("--dry-run", action="store_true", help="prikaži brisanja bez upisa")
    p_format.add_argument("--no-cleanup", action="store_true", help="ne briši prazne pasuse")
    p_format.add_argument("--lenient", action="store_true",
                          help="nastavi i kad struktura nije prepoznata")
    p_format.add_argument("--toc", action=argparse.BooleanOptionalAction, default=None,
                          help="ubaci Word TOC polje (podrazumevano po pravilima)")
    p_format.add_argument("--save-rules", action="store_true", help="sačuvaj pravila u biblioteku")
    p_format.set_defaults(func=cmd_format)

    p_extract = sub.add_parser("extract", help="izvuci pravila iz pravilnika")
    p_extract.add_argument("pravilnik")
    p_extract.add_argument("--out", help="zapiši rules JSON u fajl")
    p_extract.add_argument("--save", action="store_true", help="sačuvaj u biblioteku")
    p_extract.add_argument("--save-as", help="sačuvaj u biblioteku pod datim nazivom")
    p_extract.set_defaults(func=cmd_extract)

    p_library = sub.add_parser("library", help="upravljanje bibliotekom pravila")
    p_library.add_argument("action", choices=["list", "show", "copy", "delete", "import", "export"])
    p_library.add_argument("target", nargs="?")
    p_library.add_argument("--out")
    p_library.set_defaults(func=cmd_library)

    p_structure = sub.add_parser("structure", help="dijagnostika detekcije strukture")
    p_structure.add_argument("input")
    add_rule_source(p_structure)
    p_structure.set_defaults(func=cmd_structure)

    p_mate = sub.add_parser("mate", help="provera veze sa Mate agentom")
    p_mate.add_argument("action", nargs="?", default="ping", choices=["ping"])
    p_mate.set_defaults(func=cmd_mate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
