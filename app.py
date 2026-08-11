"""Streamlit UI za styleguard.

Dve celine: formatiranje dokumenta i upravljanje bibliotekom pravila.

Korak pregleda pravila pre primene nije ukras -- ekstrakcija iz pravilnika je
najnepouzdaniji deo lanca, pa se svako pravilo prikazuje uz poreklo, pouzdanost
i citat iz izvora, i ništa se ne primenjuje dok korisnik ne potvrdi.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

from styleguard import __version__, i18n, identity
from styleguard.i18n import t
from styleguard.extract.mate_client import MateClient, MateConfig
from styleguard.extract.pipeline import extract_rule_set, identify_institution
from styleguard.extract.source import NoTextLayerError, read_rules_document
from styleguard.formatting.engine import FormatOptions, format_document
from styleguard.library import RuleLibrary, suggest_display_name
from styleguard.rules import (
    Casing,
    Evidence,
    RuleSet,
    enum_type_for_path,
    iter_field_paths,
    load_rule_set,
    set_by_path,
)

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
REPO_URL = "https://github.com/antiv/styleguard"

st.set_page_config(
    page_title="StyleGuard",
    page_icon=str(ASSETS_DIR / "icon-192.png"),
    layout="wide",
)


# --------------------------------------------------------------------------
# Zajedničko
# --------------------------------------------------------------------------


@st.cache_resource
def get_library() -> RuleLibrary:
    return RuleLibrary()


def load_presets() -> list[RuleSet]:
    out: list[RuleSet] = []
    for path in sorted(PRESETS_DIR.glob("*.json")):
        try:
            out.append(load_rule_set(path))
        except Exception:
            continue
    return out


def mate_client() -> MateClient | None:
    config = MateConfig.from_env()
    return MateClient(config) if config.is_configured else None


@contextmanager
def temp_upload(uploaded):
    """Uploadovani fajl na disku samo dok traje obrada.

    Bitno na serveru: bez brisanja bi se tuđi pravilnici gomilali u /tmp i
    ostajali tamo neograničeno. Sam rad nikad ne dodiruje disk -- ide kroz
    `io.BytesIO`.
    """
    suffix = Path(uploaded.name).suffix
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(uploaded.getbuffer())
        handle.close()
        yield Path(handle.name)
    finally:
        Path(handle.name).unlink(missing_ok=True)


@st.cache_data(ttl=120, show_spinner=False)
def _mate_ping(base_url: str, agent: str, token_fingerprint: str) -> tuple[bool, str]:
    """Keširan ping.

    Bez keša bi se Mate zvao pri svakom preiscrtavanju strane, a Streamlit
    preiscrtava na svaki klik. Argumenti ulaze u ključ keša da bi izmena
    konfiguracije oborila keš; token se ne prosleđuje u čitavom obliku.
    """
    return MateClient(MateConfig.from_env()).ping()


def mate_status_banner() -> None:
    """Mate je opciona nadogradnja, ne zavisnost.

    Bez njega ekstrakcija radi na regex heuristici, pa odsustvo Mate-a nije
    greška i ne prikazuje se kao greška.
    """
    config = MateConfig.from_env()
    if not config.is_configured:
        st.sidebar.caption(t("mate.heuristic_only"))
        return
    ok, message = _mate_ping(config.base_url, config.agent, (config.token or "")[-6:])
    (st.sidebar.success if ok else st.sidebar.warning)(message)


# --------------------------------------------------------------------------
# Editor pravila
# --------------------------------------------------------------------------

_CONFIDENCE_ICON = {"high": "🟢", "medium": "🟡", "low": "🔴"}
def _source_label(source: str) -> str:
    return t(f"source.{source}")



def _render_evidence(evidence: Evidence | None) -> str:
    if evidence is None:
        return ""
    icon = _CONFIDENCE_ICON.get(evidence.confidence, "")
    source = _source_label(evidence.source)
    page = ", " + t("evidence.page", page=evidence.page) if evidence.page else ""
    quote = f" — „{evidence.quote}”" if evidence.quote else ""
    return f"{icon} {source}{page}{quote}"


def rules_editor(rule_set: RuleSet, key_prefix: str) -> RuleSet:
    """Editor svih skalarnih polja, grupisan po sekciji šeme."""
    unresolved = set(rule_set.unresolved)
    groups: dict[str, list[tuple[str, object]]] = {}
    for path, value in iter_field_paths(rule_set.rules):
        groups.setdefault(path.split(".", 1)[0], []).append((path, value))

    for group, fields in groups.items():
        filled = sum(1 for _, value in fields if value is not None)
        with st.expander(
            t("editor.group", group=group, filled=filled, total=len(fields)),
            expanded=group == "body",
        ):
            for path, value in fields:
                evidence = rule_set.evidence_for(path)
                columns = st.columns([3, 2, 5])

                label = path.split(".", 1)[1] if "." in path else path
                if path in unresolved:
                    label += "  ⚠️"
                columns[0].markdown(f"`{label}`")

                enum_type = enum_type_for_path(rule_set.rules, path)
                new_value = _render_input(
                    path, value, f"{key_prefix}:{path}", columns[1], enum_type
                )
                if new_value != value:
                    set_by_path(rule_set.rules, path, new_value)
                    rule_set.evidence = [e for e in rule_set.evidence if e.field_path != path]
                    if new_value is not None:
                        rule_set.evidence.append(
                            Evidence(field_path=path, confidence="high", source="manual")
                        )
                    rule_set.unresolved = [u for u in rule_set.unresolved if u != path]

                columns[2].caption(_render_evidence(evidence) or "—")

    _render_headings_editor(rule_set, key_prefix)
    _render_keywords_editor(rule_set, key_prefix)
    return rule_set


def _render_input(path: str, value, key: str, column, enum_type=None):
    """Widget koji ume da vrati `None` -- prazno polje znači 'ne diraj'."""
    if enum_type is not None:
        options = [t("editor.leave_alone")] + [member.value for member in enum_type]
        current = value.value if value is not None else t("editor.leave_alone")
        chosen = column.selectbox(
            path, options, index=options.index(current), key=key, label_visibility="collapsed"
        )
        return None if chosen == t("editor.leave_alone") else enum_type(chosen)

    if isinstance(value, bool) or path.endswith(
        ("bold", "italic", "mirror_margins", "different_first_page", "allow_italic",
         "allow_empty_paragraphs", "insert_field", "header_row_bold", "header_row_repeat",
         "page_break_before", "keep_with_next")
    ):
        options = [t("editor.leave_alone"), t("editor.yes"), t("editor.no")]
        current = (
            t("editor.leave_alone")
            if value is None
            else (t("editor.yes") if value else t("editor.no"))
        )
        chosen = column.selectbox(
            path, options, index=options.index(current), key=key, label_visibility="collapsed"
        )
        return None if chosen == t("editor.leave_alone") else chosen == t("editor.yes")

    if isinstance(value, (int, float)) or path.endswith(("_pt", "_cm", "spacing", "levels")):
        text = "" if value is None else str(value)
        entered = column.text_input(path, text, key=key, label_visibility="collapsed",
                                    placeholder=t("editor.placeholder"))
        if not entered.strip():
            return None
        try:
            return float(entered.replace(",", "."))
        except ValueError:
            column.error(t("editor.number_expected"))
            return value

    if isinstance(value, list):
        entered = column.text_input(
            path, ", ".join(str(v) for v in value), key=key, label_visibility="collapsed"
        )
        return [part.strip() for part in entered.split(",") if part.strip()]

    text = "" if value is None else str(value)
    entered = column.text_input(path, text, key=key, label_visibility="collapsed",
                                placeholder=t("editor.placeholder"))
    return entered.strip() or None


def _render_headings_editor(rule_set: RuleSet, key_prefix: str) -> None:
    with st.expander(t("editor.headings", count=len(rule_set.rules.headings))):
        if not rule_set.rules.headings:
            st.info(t("editor.headings_empty"))
        for heading in rule_set.rules.headings:
            columns = st.columns(6)
            columns[0].markdown("**" + t("editor.heading_level", level=heading.level) + "**")
            heading.size_pt = _float_input(columns[1], t("editor.pt"), heading.size_pt, f"{key_prefix}:h{heading.level}:size")
            heading.bold = _bool_input(columns[2], t("editor.bold"), heading.bold, f"{key_prefix}:h{heading.level}:bold")
            heading.casing = _casing_input(columns[3], heading.casing, f"{key_prefix}:h{heading.level}:casing")
            heading.page_break_before = _bool_input(
                columns[4], t("editor.page_break"), heading.page_break_before, f"{key_prefix}:h{heading.level}:pb"
            )
            heading.keep_with_next = _bool_input(
                columns[5], t("editor.keep_with_next"), heading.keep_with_next, f"{key_prefix}:h{heading.level}:kwn"
            )


def _render_keywords_editor(rule_set: RuleSet, key_prefix: str) -> None:
    keywords = rule_set.rules.structure_profile.section_keywords
    with st.expander(t("editor.keywords")):
        st.caption(t("editor.keywords_help"))
        for field in ("front_matter", "body_start", "bibliography", "appendix"):
            current = getattr(keywords, field)
            entered = st.text_input(
                field, ", ".join(current), key=f"{key_prefix}:kw:{field}"
            )
            setattr(keywords, field, [p.strip() for p in entered.split(",") if p.strip()])


def _float_input(column, label, value, key):
    entered = column.text_input(label, "" if value is None else str(value), key=key)
    if not entered.strip():
        return None
    try:
        return float(entered.replace(",", "."))
    except ValueError:
        return value


def _bool_input(column, label, value, key):
    none_label = t("editor.none")
    options = [none_label, t("editor.yes"), t("editor.no")]
    current = none_label if value is None else (t("editor.yes") if value else t("editor.no"))
    chosen = column.selectbox(label, options, index=options.index(current), key=key)
    return None if chosen == none_label else chosen == t("editor.yes")


def _casing_input(column, value, key):
    none_label = t("editor.none")
    options = [none_label] + [member.value for member in Casing]
    current = value.value if value is not None else none_label
    chosen = column.selectbox(
        t("editor.casing"), options, index=options.index(current), key=key
    )
    return None if chosen == none_label else Casing(chosen)


# --------------------------------------------------------------------------
# Stranica: formatiranje
# --------------------------------------------------------------------------


def page_format(user) -> None:
    library = get_library()
    st.header(t("format.header"))

    document_file = st.file_uploader(t("format.thesis"), type=["docx"], key="doc")

    st.subheader(t("format.rules_source"))
    # Jedna lista gotovih setova, ne dve. Odakle fajl dolazi -- `rules_library/`
    # ili `presets/` -- je detalj isporuke; korisnik pita samo da li pravila za
    # njegov fakultet već postoje. Razdvojeno je značilo da ko klikne
    # „iz biblioteke" i vidi prazno zaključi da nema ničega, a osamnaest setova
    # stoji jedan radio-taster dalje.
    saved = library.list()
    saved_ids = {rs.meta.id for rs in saved}
    bundled = [p for p in load_presets() if p.meta.id not in saved_ids]
    bundled_ids = {p.meta.id for p in bundled}
    available = saved + bundled

    sources = {
        "upload": t("format.source.upload"),
        "library": t("format.source.library"),
        "json": t("format.source.json"),
    }
    source = st.radio(
        t("format.rules_source"),
        list(sources),
        format_func=lambda key: sources[key],
        horizontal=True,
        label_visibility="collapsed",
    )

    rule_set: RuleSet | None = st.session_state.get("rule_set")

    if source == "upload":
        rules_file = st.file_uploader(t("format.guide_file"), type=["pdf", "docx"], key="rules")
        if rules_file and st.button(t("format.extract"), type="primary"):
            rule_set = _extract_flow(rules_file, library)
            st.session_state["rule_set"] = rule_set

    elif source == "library":
        if not available:
            st.info(t("format.library_empty"))
        else:
            def label(rs: RuleSet) -> str:
                mark = f" · {t('library.bundled')}" if rs.meta.id in bundled_ids else ""
                return f"{rs.meta.display_name}  ({rs.meta.id}){mark}"

            chosen = st.selectbox(t("format.set"), available, format_func=label)
            if st.button(t("format.load"), type="primary"):
                # Priložen set se kopira, ne učitava: izmene u editoru ne smeju
                # da završe u fajlu koji je deo isporuke.
                rule_set = (
                    chosen.model_copy(deep=True)
                    if chosen.meta.id in bundled_ids
                    else library.load(chosen.meta.id)
                )
                st.session_state["rule_set"] = rule_set

    else:
        json_file = st.file_uploader("rules.json", type=["json"], key="rules_json")
        if json_file and st.button(t("format.load"), type="primary"):
            rule_set = RuleSet.model_validate_json(json_file.getvalue().decode("utf-8"))
            st.session_state["rule_set"] = rule_set

    if rule_set is None:
        return

    st.divider()
    st.subheader(t("format.rules_heading", name=rule_set.meta.display_name))
    if rule_set.unresolved:
        st.warning(t("format.unresolved", count=len(rule_set.unresolved)))
    rule_set = rules_editor(rule_set, key_prefix="fmt")
    st.session_state["rule_set"] = rule_set

    _save_to_library_controls(rule_set, library, user)

    if document_file is None:
        st.info(t("format.need_docx"))
        return

    st.divider()
    st.subheader(t("format.apply"))
    columns = st.columns(3)
    cleanup = columns[0].checkbox(t("format.clean_empty"), value=True)
    lenient = columns[1].checkbox(t("format.lenient"), value=False)
    toc_options = {
        None: t("format.toc.by_rules"),
        True: t("format.toc.insert"),
        False: t("format.toc.skip"),
    }
    toc_choice = columns[2].selectbox(
        t("format.toc"), list(toc_options), format_func=lambda key: toc_options[key]
    )

    options = FormatOptions(
        strict_structure=not lenient,
        clean_empty_paragraphs=cleanup,
        insert_toc=toc_choice,
    )

    if st.button(t("format.preview_deletions"), width='stretch'):
        _run_format(document_file, rule_set, FormatOptions(**{**options.__dict__, "dry_run": True}))

    if st.button(t("format.run"), type="primary", width='stretch'):
        _run_format(document_file, rule_set, options, offer_download=True)


def _extract_flow(rules_file, library: RuleLibrary) -> RuleSet | None:
    try:
        with temp_upload(rules_file) as path:
            document = read_rules_document(path)
    except NoTextLayerError as exc:
        st.error(str(exc))
        return None
    except ValueError as exc:
        st.error(str(exc))
        return None

    client = mate_client()

    with st.status(t("extract.identifying"), expanded=True) as status:
        institution, origin = identify_institution(document, client)
        st.write(
            t(
                "extract.institution",
                origin=origin,
                name=suggest_display_name(institution) or t("extract.institution_unknown"),
            )
        )

        matches = library.find_matches(institution)
        if matches and (matches[0].is_strong or matches[0].is_suggestion):
            best = matches[0]
            status.update(label=t("extract.match_found"), state="complete")
            st.session_state["pending_match"] = best.rule_set.meta.id
            st.info(
                t(
                    "extract.match_details",
                    name=best.rule_set.meta.display_name,
                    score=f"{best.score:.2f}",
                )
            )

        status.update(label=t("extract.extracting"), state="running")
        outcome = extract_rule_set(
            document, client=client, library=library, institution=institution,
            on_progress=lambda msg: st.write(msg),
        )
        status.update(label=t("extract.done", source=outcome.source), state="complete")

    for warning in outcome.warnings:
        st.warning(warning)
    if outcome.rejected:
        st.error(t("extract.rejected", fields=", ".join(outcome.rejected)))
    return outcome.rule_set


def _save_to_library_controls(rule_set: RuleSet, library: RuleLibrary, user) -> None:
    with st.expander(t("save.expander")):
        if not identity.can_create(user):
            st.caption(t("save.requires_login"))
            st.download_button(
                t("save.download_json"),
                rule_set.model_dump_json(indent=2),
                file_name=f"{rule_set.meta.id}.json",
                mime="application/json",
            )
            return

        # Postojeći tuđi set se ne prepisuje: snimanje pravi novi, u vlasništvu
        # onoga ko snima. Original ostaje netaknut.
        existing = library.load(rule_set.meta.id) if library.exists(rule_set.meta.id) else None
        overwriting = existing is not None and identity.can_edit(existing, user)
        if existing is not None and not overwriting:
            st.caption(t("save.foreign", name=existing.meta.display_name))

        columns = st.columns([4, 1])
        name = columns[0].text_input(t("save.name"), rule_set.meta.display_name, key="save_name")
        if columns[1].button(t("save.button"), width='stretch'):
            if name != rule_set.meta.display_name:
                rule_set.meta.display_name = name
            if not overwriting:
                rule_set.meta.id = library.unique_id(name)
            rule_set.meta.owner = user.email
            rule_set.meta.owner_name = user.name
            library.save(rule_set)
            st.success(t("save.saved", id=rule_set.meta.id))
        st.download_button(
            t("save.download_json"),
            rule_set.model_dump_json(indent=2),
            file_name=f"{rule_set.meta.id}.json",
            mime="application/json",
        )


def _run_format(document_file, rule_set: RuleSet, options: FormatOptions, offer_download: bool = False) -> None:
    try:
        result = format_document(io.BytesIO(document_file.getbuffer()), rule_set, options)
    except Exception as exc:
        st.error(t("format.failed", error=exc))
        return

    report = result.report
    columns = st.columns(3)
    columns[0].metric(t("report.style_changes"), len(report.style_changes))
    columns[1].metric(t("report.deletions"), len(report.deletions))
    columns[2].metric(t("report.insertions"), len(report.insertions))

    for warning in report.warnings:
        st.warning(warning)

    if report.style_changes:
        st.dataframe(
            [
                {
                    t("report.col.role"): s.role or "—",
                    t("report.col.property"): s.rule_path,
                    t("report.col.count"): s.count,
                    t("report.col.changes"): s.describe_transitions(),
                }
                for s in report.by_rule()
            ],
            width='stretch',
            hide_index=True,
        )

    if report.deletions:
        with st.expander(
            t("report.deletions_expander", count=len(report.deletions)),
            expanded=options.dry_run,
        ):
            st.dataframe(
                [
                    {
                        t("report.col.paragraph"): c.paragraph_index,
                        t("report.col.section"): c.section,
                        t("report.col.what"): c.detail,
                    }
                    for c in report.deletions
                ],
                width='stretch',
                hide_index=True,
            )

    if offer_download:
        name = Path(document_file.name).stem
        st.download_button(
            t("format.download"),
            result.to_bytes(),
            file_name=f"Formatiran_{name}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            width='stretch',
        )


# --------------------------------------------------------------------------
# Stranica: biblioteka
# --------------------------------------------------------------------------


def page_library(user) -> None:
    library = get_library()
    st.header(t("library.header"))

    if user is None:
        st.info(t("library.anonymous"))
    elif user.is_admin:
        st.caption(t("library.admin"))

    # Priloženi preseti se prikazuju ovde zajedno sa snimljenim setovima. Bez
    # toga su nevidljivi: biblioteka je prvo mesto na kome ih korisnik traži, a
    # oni su dotad postojali samo kao izvor pravila na strani za formatiranje.
    saved = library.list()
    saved_ids = {rs.meta.id for rs in saved}
    bundled = [p for p in load_presets() if p.meta.id not in saved_ids]
    bundled_ids = {p.meta.id for p in bundled}
    sets = saved + bundled

    if not sets:
        st.info(t("library.empty"))
    else:
        st.dataframe(
            [
                {
                    t("library.col.name"): rs.meta.display_name,
                    t("library.col.owner"): (
                        t("library.bundled")
                        if rs.meta.id in bundled_ids
                        else rs.meta.owner_name or rs.meta.owner or t("library.builtin")
                    ),
                    t("library.col.university"): rs.meta.institution.university or "—",
                    t("library.col.faculty"): rs.meta.institution.faculty or "—",
                    t("library.col.type"): rs.meta.institution.document_type or "—",
                    t("library.col.updated"): rs.meta.updated_at.strftime("%Y-%m-%d %H:%M"),
                }
                for rs in sets
            ],
            width='stretch',
            hide_index=True,
        )

        chosen = st.selectbox(
            t("library.set"), sets,
            format_func=lambda rs: f"{rs.meta.display_name}  ({rs.meta.id})",
        )
        # Preset je fajl isporučen uz aplikaciju, ne podatak instance: izmena bi
        # nestala pri sledećem redeployu, a brisanje bi se vratilo. Kopija je
        # jedini put koji vodi negde, pa je jedina ponuđena.
        is_bundled = chosen.meta.id in bundled_ids
        may_edit = identity.can_edit(chosen, user) and not is_bundled
        st.caption(
            t("library.bundled_hint")
            if is_bundled
            else identity.describe_permission(chosen, user)
        )

        columns = st.columns(4)
        if columns[0].button(t("library.edit"), width='stretch', disabled=not may_edit):
            st.session_state["editing"] = chosen.meta.id
        # Kopiranje je namerno dozvoljeno svakome ko je prijavljen, i nad tuđim
        # setom: to je izlaz koji zabranu izmene čini neblokirajućom.
        if columns[1].button(
            t("library.copy"), width='stretch', disabled=not identity.can_create(user)
        ):
            copy = library.duplicate_of(chosen)
            copy.meta.owner = user.email
            copy.meta.owner_name = user.name
            library.save(copy)
            st.success(t("library.copied", id=copy.meta.id))
            st.rerun()
        if columns[2].button(t("library.delete"), width='stretch', disabled=not may_edit):
            library.delete(chosen.meta.id)
            st.session_state.pop("editing", None)
            st.rerun()
        columns[3].download_button(
            t("library.export"),
            chosen.model_dump_json(indent=2),
            file_name=f"{chosen.meta.id}.json",
            mime="application/json",
            width='stretch',
        )

        editing = st.session_state.get("editing")
        if editing and library.exists(editing):
            rule_set = library.load(editing)
            # Dozvola se proverava i ovde, ne samo na dugmetu: `editing` preživi
            # u sesiji, pa odjava ili izbor tuđeg seta ne sme da ostavi otvoren
            # editor sa aktivnim snimanjem.
            if not identity.can_edit(rule_set, user):
                st.session_state.pop("editing", None)
                st.rerun()

            st.divider()
            st.subheader(t("library.editing", name=rule_set.meta.display_name))

            institution = rule_set.meta.institution
            columns = st.columns(4)
            rule_set.meta.display_name = columns[0].text_input(
                t("library.name"), rule_set.meta.display_name
            )
            institution.university = columns[1].text_input(
                t("library.university"), institution.university or ""
            ) or None
            institution.faculty = columns[2].text_input(
                t("library.faculty"), institution.faculty or ""
            ) or None
            institution.document_type = columns[3].text_input(
                t("library.document_type"), institution.document_type or ""
            ) or None

            rule_set = rules_editor(rule_set, key_prefix=f"lib:{editing}")
            if st.button(t("library.save_changes"), type="primary"):
                library.save(rule_set)
                st.success(t("library.saved"))
                st.rerun()

    st.divider()
    if identity.can_create(user):
        uploaded = st.file_uploader(t("library.import_file"), type=["json"], key="import_json")
        if uploaded and st.button(t("library.import")):
            with temp_upload(uploaded) as path:
                imported = library.import_(path)
            # Uvezen set pripada onome ko ga je uveo, bez obzira na to čiji je
            # bio u fajlu -- inače bi uvoz mogao da podmetne tuđe vlasništvo.
            imported.meta.owner = user.email
            imported.meta.owner_name = user.name
            library.save(imported)
            st.success(t("library.imported", id=imported.meta.id))
            st.rerun()


# --------------------------------------------------------------------------


def _apply_language() -> None:
    """Set the language for this session before anything is rendered.

    The browser's `Accept-Language` decides the first impression; once the user
    picks from the selector, that choice wins for the rest of the session.
    """
    chosen = st.session_state.get("language")
    if chosen is None:
        try:
            header = st.context.headers.get("Accept-Language")
        except Exception:
            header = None
        chosen = i18n.negotiate(header)
        st.session_state["language"] = chosen
    i18n.set_language(chosen)


def page_help() -> None:
    """Opis aplikacije, uputstvo i -- najvažnije -- šta se dešava sa dokumentima.

    Tvrdnje o privatnosti ovde moraju da odgovaraju kodu, ne marketingu:
    rad zaista nikad ne dodiruje disk (`format_document` ga čita iz
    `io.BytesIO`), a pravilnik dodiruje samo privremeno jer pdfplumber traži
    pravi fajl, pa se briše u `finally` (`temp_upload`). Na model odlazi tekst
    pravilnika, nikad tekst rada.
    """
    heading, closer = st.columns([12, 1])
    heading.header(t("help.header"))
    # `st.rerun()` je ovde bezbedan: radio je već renderovan u `main()`, pa mu
    # stanje preživljava. Isti poziv pre radija ga je ranije brisao.
    if closer.button("✕", key="help_close", help=t("help.close")):
        st.session_state["help_open"] = False
        st.rerun()
    st.write(t("help.intro"))

    st.subheader(t("help.how.title"))
    st.markdown(t("help.how.body"))

    st.subheader(t("help.privacy.title"))
    st.success(t("help.privacy.lead"))
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{t('help.privacy.thesis.title')}**")
        st.markdown(t("help.privacy.thesis.body"))
    with right:
        st.markdown(f"**{t('help.privacy.guide.title')}**")
        st.markdown(t("help.privacy.guide.body"))
    st.markdown(f"**{t('help.privacy.stored.title')}**")
    st.markdown(t("help.privacy.stored.body"))
    if not MateConfig.from_env().is_configured:
        # Bez agenta ništa ne napušta server, i to je vest koju korisnik želi.
        st.info(t("help.privacy.offline"))

    st.subheader(t("help.invariants.title"))
    st.markdown(t("help.invariants.body"))

    st.subheader(t("help.library.title"))
    st.markdown(t("help.library.body"))

    st.subheader(t("help.faq.title"))
    for number in range(1, 6):
        with st.expander(t(f"help.faq.q{number}")):
            st.markdown(t(f"help.faq.a{number}"))

    st.subheader(t("help.opensource.title"))
    st.markdown(t("help.opensource.body"))
    st.link_button(t("help.opensource.button"), REPO_URL)


def _language_selector() -> None:
    languages = list(i18n.available_languages())
    current = st.session_state.get("language", i18n.DEFAULT_LANGUAGE)
    picked = st.sidebar.selectbox(
        t("app.language"),
        languages,
        index=languages.index(current) if current in languages else 0,
        format_func=i18n.language_name,
        key="language_picker",
    )
    if picked != current:
        st.session_state["language"] = picked
        st.rerun()


def main() -> None:
    _apply_language()

    if not identity.require_gate(st):
        return

    user = identity.current_user(st)

    st.logo(str(ASSETS_DIR / "icon-192.png"), size="large")
    st.sidebar.title(t("app.title"))
    identity.render_sidebar(st, user)
    st.sidebar.divider()
    mate_status_banner()

    pages = {"format": t("app.page.format"), "library": t("app.page.library")}

    # Pomoć nije stavka navigacije nego preklop preko nje: otvara je sopstveno
    # dugme, a zatvara izbor bilo koje strane.
    def close_help() -> None:
        st.session_state["help_open"] = False

    # Dugme samo otvara; zatvara se sa ✕ na samoj strani ili izborom druge
    # strane. Boja se namerno ne menja: `type` bi se računao iz stanja pre
    # prekidanja, a pošto ovde nema rerun-a, dugme bi bilo crveno tačno onda kad
    # je pomoć zatvorena -- obrnuto od onoga što bi boja trebalo da znači.
    #
    # Bez `st.rerun()` ovde. Klik ionako pokreće nov prolaz, a rerun pre radija
    # bi odbacio stanje widgeta koji u tom prolazu nije stigao da se renderuje
    # -- `nav` bi nestao i izbor strane bi se vratio na početak.
    if st.sidebar.button(f"ℹ️ {t('app.page.help')}", key="help_button", width="stretch"):
        st.session_state["help_open"] = True
    help_open = st.session_state.get("help_open", False)

    page = st.sidebar.radio(
        t("app.page"),
        list(pages),
        key="nav",
        on_change=close_help,
        format_func=lambda key: pages[key],
    )
    _language_selector()
    st.sidebar.divider()
    st.sidebar.caption(t("app.promise"))
    # Verzija nije prevodiva -- broj izdanja je isti na svakom jeziku.
    st.sidebar.caption(f"v{__version__}")

    if help_open:
        page_help()
    elif page == "format":
        page_format(user)
    else:
        page_library(user)


if __name__ == "__main__":
    main()
