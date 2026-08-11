"""Pretraga setova pravila po slobodnom tekstu.

Odvojeno od `library._normalize`, koje služi *poređenju institucija* i zato
izbacuje stop-reči i propušta samo ASCII. Za pretragu su oba pogrešna: ko
otkuca „fakultet" očekuje pogotke, a ćirilični set bi kroz `encode("ascii")`
ostao bez ijednog slova i postao nenalaziv.

Ovde se umesto toga ćirilica preslovljava. Skopski set nosi „Скопје" u nazivu,
a korisnik ga traži kucajući „skopje" -- bez preslovljavanja ta dva se nikad ne
bi srela.
"""

from __future__ import annotations

import re
import unicodedata

# Srpska i makedonska ćirilica u latinicu. Preslikavanje je namerno gubitno
# (ж i з oba idu u „z"), jer se izlaz ionako svodi na ASCII radi poređenja.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ѓ": "g", "ђ": "dj",
    "е": "e", "ж": "z", "з": "z", "ѕ": "dz", "и": "i", "ј": "j", "к": "k",
    "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "ќ": "k", "ћ": "c", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "c", "џ": "dz", "ш": "s",
}


def fold(value: str | None) -> str:
    """Tekst sveden na mala ASCII slova i cifre, razdvojen razmakom.

    Dijakritika otpada, pa „Niš" i „nis" postaju isto; ćirilica se preslovljava
    pre nego što se ostatak odbaci.
    """
    if not value:
        return ""
    lowered = value.lower()
    transliterated = "".join(_CYRILLIC.get(char, char) for char in lowered)
    decomposed = unicodedata.normalize("NFKD", transliterated)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = stripped.replace("đ", "dj").replace("ß", "ss")
    ascii_only = stripped.encode("ascii", "ignore").decode("ascii")
    return " ".join(t for t in re.split(r"[^a-z0-9]+", ascii_only) if t)


def haystack(rule_set) -> str:
    """Sve po čemu ima smisla tražiti set: naziv, id i institucija."""
    meta = rule_set.meta
    institution = meta.institution
    parts = [
        meta.display_name,
        meta.id,
        institution.university,
        institution.faculty,
        institution.department,
        institution.organization,
        institution.document_type,
        institution.language,
    ]
    return fold(" ".join(p for p in parts if p))


# Prag je namerno popustljiv: promena u našim padežima zna da pojede i dva
# slova („Rijeka" -> „Rijeci", „Banja" -> „Banjoj"), a kratki upiti se ionako
# hvataju podnizom, pa ovde ne prave lažne pogotke.
_MIN_STEM = 3
_STEM_RATIO = 0.6


def _same_stem(token: str, word: str) -> bool:
    """Da li se dve reči razlikuju samo u nastavku.

    Korisnik kuca nominativ -- „Sarajevo", „Ljubljana" -- a u pravilniku stoji
    „u Sarajevu", „v Ljubljani". Bez ovoga pretraga po imenu grada ne nalazi
    ništa, što je za publiku u regionu prvi način na koji će je upotrebiti.
    """
    common = 0
    for a, b in zip(token, word):
        if a != b:
            break
        common += 1
    if common < _MIN_STEM:
        return False
    return common >= _STEM_RATIO * max(len(token), len(word))


def score(rule_set, query: str) -> int:
    """Koliko reči upita se našlo u setu.

    Rangiranje, a ne filtriranje po svim rečima. „Banja Luka" u pravilniku
    stoji kao „Banjoj Luci"; „Luka" -> „Luci" menja koren pa se ne pogađa
    nikakvim poređenjem nastavaka. Da se tražilo poklapanje svih reči, upit
    „banja luka" ne bi vratio ništa, iako „banja" sam vraća tačan set -- a
    pretraga u kojoj duže kucanje daje manje rezultata je gora od nikakve.
    """
    tokens = fold(query).split()
    if not tokens:
        return 0
    text = haystack(rule_set)
    words = text.split()
    return sum(
        1
        for token in tokens
        if token in text or any(_same_stem(token, word) for word in words)
    )


def matches(rule_set, query: str) -> bool:
    """Da li set uopšte odgovara upitu."""
    return not fold(query) or score(rule_set, query) > 0


def search(rule_sets, query: str) -> list:
    """Setovi koji odgovaraju upitu, najbolji prvi.

    Sortiranje je stabilno, pa setovi sa istim brojem pogodaka zadržavaju
    redosled kojim su stigli -- snimljeni pre priloženih.
    """
    if not fold(query):
        return list(rule_sets)
    scored = [(score(rs, query), rs) for rs in rule_sets]
    hits = [(n, rs) for n, rs in scored if n > 0]
    hits.sort(key=lambda pair: -pair[0])
    return [rs for _, rs in hits]
