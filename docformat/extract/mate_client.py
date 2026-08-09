"""Klijent za Mate agenta preko OpenAI-kompatibilne rute.

Mate izlaže agente na `POST /v1/chat/completions` (`server/openai_routes.py`).
Dva ponašanja te rute diktiraju oblik ovog klijenta:

1. `session_id` se izvodi iz md5 hash-a **prve** poruke u nizu, ne iz cele
   konverzacije. Bez razlikovanja prve poruke svi pozivi bi delili jednu
   serversku sesiju i gomilali istoriju kroz nepovezane dokumente. Zato
   `MateSession` drži prvu poruku fiksnom i uz nju šalje samo poslednju --
   istoriju čuva ADK na serverskoj strani.
2. Ruta je text-only: ne-tekstualni blokovi se odbacuju, a novi ADK message se
   gradi kao `[{"text": ...}]`. PDF se zato nikad ne šalje kao fajl.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import requests

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_AGENT = "doc_rules_extractor"
DEFAULT_TIMEOUT = 600.0


class MateError(RuntimeError):
    """Greška u komunikaciji sa Mate-om, sa porukom namenjenom korisniku."""


class MateNotConfigured(MateError):
    pass


@dataclass
class MateConfig:
    base_url: str = DEFAULT_BASE_URL
    token: str | None = None
    agent: str = DEFAULT_AGENT
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "MateConfig":
        return cls(
            base_url=os.getenv("MATE_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            token=os.getenv("MATE_PAT") or os.getenv("MATE_TOKEN"),
            agent=os.getenv("MATE_AGENT_NAME", DEFAULT_AGENT),
            timeout=float(os.getenv("MATE_TIMEOUT", DEFAULT_TIMEOUT)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token)


class MateClient:
    def __init__(self, config: MateConfig | None = None) -> None:
        self.config = config or MateConfig.from_env()

    # -- niski nivo ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.config.token:
            raise MateNotConfigured(
                "MATE_PAT nije postavljen. Napravi Personal Access Token u Mate "
                "dashboardu (korisnik mora imati rolu 'admin' ili 'developer') i "
                "postavi ga u MATE_PAT."
            )
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.ok:
            return
        detail = ""
        try:
            detail = response.json().get("detail", "")
        except Exception:
            detail = response.text[:300]

        if response.status_code in (401, 403):
            raise MateError(
                f"Mate je odbio autentifikaciju ({response.status_code}). "
                "Proveri MATE_PAT i da korisnik ima rolu 'admin' ili 'developer'. "
                f"Detalj: {detail}"
            )
        if response.status_code == 404:
            raise MateError(
                f"Agent '{self.config.agent}' nije dostupan preko /v1 rute. "
                "U Mate dashboardu agent mora imati 'expose_as_model' uključeno, "
                "biti root agent (bez roditelja) i ne sme biti disabled. "
                f"Detalj: {detail}"
            )
        raise MateError(f"Mate je vratio HTTP {response.status_code}. Detalj: {detail}")

    # -- javni API -------------------------------------------------------

    def list_models(self) -> list[str]:
        """Agenti izloženi kao modeli -- provera povezanosti za UI."""
        try:
            response = requests.get(
                f"{self.config.base_url}/v1/models",
                headers=self._headers(),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise MateError(f"Mate nije dostupan na {self.config.base_url}: {exc}") from exc
        self._raise_for_status(response)
        return [m["id"] for m in response.json().get("data", [])]

    def ping(self) -> tuple[bool, str]:
        """(dostupan, poruka) -- nikad ne baca, namenjeno UI banneru."""
        try:
            models = self.list_models()
        except MateError as exc:
            return False, str(exc)
        if self.config.agent not in models:
            return False, (
                f"Mate je dostupan, ali agent '{self.config.agent}' nije na listi "
                f"izloženih modela ({', '.join(models) or 'lista je prazna'})."
            )
        return True, f"Mate je dostupan, agent '{self.config.agent}' je spreman."

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.config.agent,
            "messages": messages,
            "stream": False,
        }
        try:
            response = requests.post(
                f"{self.config.base_url}/v1/chat/completions",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise MateError(f"Poziv Mate agentu nije uspeo: {exc}") from exc

        self._raise_for_status(response)

        try:
            choices = response.json()["choices"]
            return choices[0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise MateError(f"Neočekivan oblik odgovora od Mate-a: {response.text[:300]}") from exc


@dataclass
class MateSession:
    """Jedna serverska sesija, vezana za jedan dokument.

    Prva poruka se nikad ne menja jer određuje `session_id` na Mate strani;
    naredni pozivi (npr. repair krug) šalju je nepromenjenu uz novu poruku, pa
    agent zadrži kontekst dokumenta bez ponovnog slanja celog teksta.
    """

    client: MateClient
    discriminator: str
    _seed: str | None = field(default=None, init=False, repr=False)

    def _tag(self) -> str:
        digest = hashlib.sha256(self.discriminator.encode("utf-8")).hexdigest()[:16]
        return f"[session: {digest}]"

    def send(self, text: str) -> str:
        if self._seed is None:
            self._seed = f"{self._tag()}\n{text}"
            return self.client.complete([{"role": "user", "content": self._seed}])
        return self.client.complete(
            [
                {"role": "user", "content": self._seed},
                {"role": "user", "content": text},
            ]
        )
