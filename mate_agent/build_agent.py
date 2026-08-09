#!/usr/bin/env python3
"""Generiše Mate agent template iz `styleguard.extract.prompt.AGENT_INSTRUCTION`.

Instrukcija živi u Python kodu i odavde se prepisuje u JSON, da ne postoje dve
kopije koje se vremenom raziđu. Kad se instrukcija promeni:

    .venv/bin/python mate_agent/build_agent.py

pa se rezultat ponovo importuje u Mate dashboard (Agents -> Import JSON).

JSON *šema* pravila namerno nije deo agenta -- ide u svaku poruku iz
`prompt.build_extract_payload`, pa izmena `rules.py` ne traži novi import.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from styleguard.extract.prompt import AGENT_INSTRUCTION  # noqa: E402

OUTPUT = Path(__file__).resolve().parent / "doc_rules_extractor.json"

AGENT_NAME = "doc_rules_extractor"

template = {
    "export_info": {
        "version": "1.0",
        "root_agent": AGENT_NAME,
        "total_agents": 1,
        "generated_by": "mate_agent/build_agent.py",
    },
    "agents": [
        {
            "name": AGENT_NAME,
            "type": "llm",
            # Zadatak je striktna transformacija teksta u JSON, nad ulazom koji
            # ume da bude i 100k+ karaktera -- otuda model sa velikim kontekstom
            # koji pouzdano poštuje traženi format odgovora. Menja se u Mate
            # dashboardu bez ponovnog generisanja ovog fajla.
            "model_name": "openrouter/deepseek/deepseek-v4-flash",
            "description": (
                "Pretvara tekst akademskog pravilnika o formatiranju (PDF/DOCX, "
                "sl/sr/hr/en) u strukturiran JSON objekat pravila, sa citatom iz "
                "izvora kao dokazom za svako pravilo."
            ),
            "instruction": AGENT_INSTRUCTION,
            # Root agent bez roditelja + expose_as_model: bez oba, /v1/chat/completions
            # vraća 404 (server/openai_routes.py filtrira upravo po tome).
            "parent_agents": [],
            "expose_as_model": True,
            # Bez alata namerno: zadatak je čista transformacija teksta, a svaki
            # dodatni alat samo povećava šansu da model odgovori nečim što nije JSON.
            "tool_config": "{}",
            "mcp_servers_config": "",
            "guardrail_config": "{}",
            # RBAC nad samim agentom -- odvojena provera od one koja odlučuje ko
            # sme na /v1 rutu (`ALLOWED_API_ROLES`, podrazumevano admin+developer).
            # Ovde mora biti i `user`, jer je to rola koju obični nalozi nose;
            # bez nje agent odgovara praznim sadržajem uz RBAC denied u logu.
            "allowed_for_roles": json.dumps(["admin", "developer", "user"]),
            "disabled": False,
            "hardcoded": False,
        }
    ],
    "memory_blocks": [],
}


def main() -> None:
    OUTPUT.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Zapisano: {OUTPUT}")
    print(f"Instrukcija: {len(AGENT_INSTRUCTION)} karaktera")


if __name__ == "__main__":
    main()
