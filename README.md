# Antigravity Swarm Coordinator (Long-Horizon V4.1)

Kompletní záloha a instalační balíček výchozího **Swarm Koordinátoru** a multi-agentního řídicího rámce pro **Google Antigravity** a **Gemini CLI**.

Tento repozitář obsahuje celou architekturu koordinátora včetně globálního konfiguračního promptu, governance pravidel, validačních skriptů, sady 21 specializovaných dovedností (skills), ASW pluginu (`antigravity-swarm`) a šablon pro řízení rozsáhlých vývojových i kvantitativních výzkumných programů.

---

## 🏗️ Architektura a principy fungování

Swarm koordinátor v Antigravity funguje jako **jediný globální orchestrátor (Single Orchestrator Rule)**, který řídí provádění úloh, rozpad plánů, životní cyklus agentů a mechanickou i sémantickou integritu.

```
                    ┌────────────────────────────────────────┐
                    │       ~/.gemini/GEMINI.md              │
                    │   (Globální vstupní bod & pravidla)    │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │           swarm-coordinator            │
                    │      (Hlavní globální orchestrátor)     │
                    └───────┬────────────────────────┬───────┘
                            │                        │
            ┌───────────────┴────────┐       ┌───────┴───────────────┐
            │   Multi-Agent Roles    │       │   ASW Engine Plugin   │
            │   (Max 8 skills budget)│       │  (antigravity-swarm)  │
            ├────────────────────────┤       ├───────────────────────┤
            │ spec-product-analyst   │       │ asw-planner           │
            │ software-architect     │       │ asw-loop              │
            │ implementation-dev     │       │ asw-reviewer          │
            │ interaction-e2e-tester │       │ asw-plan-auditor      │
            │ validator-build-test   │       │ asw-librarian         │
            │ opposition-reviewer    │       │ asw-explorer          │
            └───────────────┬────────┘       └───────┬───────────────┘
                            │                        │
                            └───────────┬────────────┘
                                        │
                                        ▼
             ┌─────────────────────────────────────────────────────┐
             │       Multi-Auditor Completion & Verification       │
             ├──────────────────────────┬──────────────────────────┤
             │   completion-auditor     │ semantic-completion-     │
             │ (Mechanická kontrola     │         auditor          │
             │ grafu úkolů a artefaktů) │ (Sémantická integrita,   │
             │                          │  invariace a hypotézy)   │
             └──────────────────────────┴──────────────────────────┘
```

### Hlavní zásady
1. **Single Orchestrator:** `swarm-coordinator` je jedinou autoritou pro globální stav a rozpad úloh. Pomocné nástroje (ASW, Conductor) slouží výhradně jako lokalizované sub-workflow.
2. **Omezený rozpočet dovedností (Skill Budget):** Maximálně **8 aktivních dovedností** v kontextu na jednu dílčí úlohu (leaf task). Zabraňuje zahlcení kontextového okna.
3. **Ohraničení subagenti:** Maximálně **4 paralelní nezávislí subagenti** najednou. Subagenti mají přísný kontrakt a nesmí sami prohlašovat globální dokončení projektu.
4. **Serializace stavu:** Paralelní agenti nesmí editovat překrývající se soubory. Koordinátor serializuje zápisy do sdíleného stavu.
5. **Dual Control Plane (V4.1 Semantic Integrity):**
   - **Mechanical Completion:** Jsou všechny úkoly a artefakty vytvořeny?
   - **Semantic Integrity:** Řešil program původní zadání za původních pravidel bez tichého posouvání hranic a metrik?

---

## ⚡ Exekuční režimy (Modes 0 až 5)

| Režim | Název | Účel & Pravidla |
| :--- | :--- | :--- |
| **Mode 0** | Operational Fast Path | Přímočaré operace (build, test, run, lint). Pouze Coordinator + Validator, žádná administrativa. |
| **Mode 1** | Investigation Only | Analýza, reprodukce chyb a diagnostika bez úprav kódu. Žádné mutace stavu. |
| **Mode 2** | Small Controlled Change | Menší kontrolovaná oprava/úprava s jasným testem a záznamem o změně. |
| **Mode 3** | Complex Delivery | Komplexní funkce: specifikace & návrh ➔ schválení uživatelem ➔ autonomní implementace ➔ QA ➔ handoff. |
| **Mode 4** | Emergency Restore | Rychlé vrácení či minimální obnova funkčnosti bez oportunitního refaktoringu. |
| **Mode 5** | Long-Horizon Program / Research | Dlouhodobé programy: zmrazení `SOURCE_PLAN.md`, `REQUIREMENT_COVERAGE.csv`, `TASK_GRAPH.json`, multi-auditor verifikace. |

---

## 📁 Struktura repozitáře

```
antigravity_swarm_coordinator/
├── README.md                          # Tato dokumentace
├── install.ps1                        # Automatický instalační a obnovovací skript (PowerShell)
├── .gitignore                         # Ochrana před commitováním cache a dočasných logů
│
├── global_entrypoint/
│   └── GEMINI.md                      # Globální instrukce instalované do ~/.gemini/GEMINI.md
│
├── core_framework/                    # Jádro řídicího rámce Long-Horizon V4.1
│   ├── rules/
│   │   └── GLOBAL_DEVELOPMENT_RULES.md # Kompletní soubor vývojových a bezpečnostních pravidel
│   ├── docs/
│   │   ├── V4_1_OPERATOR_GUIDE.md     # Příručka pro sémantickou integritu
│   │   └── ANTIGRAVITY_LONG_HORIZON_AUDIT_V4.md # Audit a teoretické základy V4
│   ├── scripts/                       # Validační a kontrolní skripty v Pythonu
│   │   ├── validate_program_state.py  # Striktní mechanický validátor stavu programu a grafu úkolů
│   │   ├── validate_agent_state.py    # Kontrola konzistence runtime stavu
│   │   ├── run_semantic_audit.py      # Kontrola sémantické integrity
│   │   ├── run_invariant_audit.py     # Kontrola neměnnosti invariancí
│   │   ├── run_report_consistency_audit.py # Detekce rozporů mezi reporty
│   │   └── migrate_v4_to_v4_1.py      # Nástroj pro migraci ze starší verze
│   ├── semantic/                      # Python engine sémantické integrity (auditor, claims, memory, ...)
│   ├── skills/                        # 21 specializovaných dovedností koordinátora a agentů
│   └── templates/                     # Standardizované šablony pro řízení projektů (Mode 2, 3, 5)
│
├── plugins/
│   └── antigravity-swarm/             # Výchozí plugin Antigravity Swarm (ASW)
│       ├── plugin.json                # Manifest pluginu (v0.2.4)
│       ├── agents/                    # ASW subagenti (asw-planner, asw-reviewer, atd.)
│       ├── hooks/                     # ASW hooky pro životní cyklus úloh
│       ├── scripts/                   # Spouštěcí a diagnostické skripty (Node.js/ESM)
│       └── skills/                    # ASW pomocné dovednosti (asw-plan, asw-loop, asw-goal, ...)
│
└── .antigravity/                      # Připravený adresář k okamžitému nakopírování do libovolného projektu
```

---

## 🛠️ Seznam zahrnutých rolí a dovedností (Skills)

Repozitář obsahuje všech **21 specializovaných dovedností**:

1. **`swarm-coordinator`**: Hlavní řídicí orchestrátor.
2. **`skill-router`**: Dynamický směrovač dovedností hlídející rozpočet (max 8).
3. **`program-state-controller`**: Správce stavového automatu, task graphu a ledgerů.
4. **`spec-product-analyst`**: Analytik požadavků, akceptačních kritérií a non-goals.
5. **`software-architect`**: Architektura, hranice komponent a API design.
6. **`ui-ux-designer`**: Stavový prostor a UX rozhraní.
7. **`implementation-developer`**: Ohraničený vývoj pod přísným kontraktem.
8. **`interaction-e2e-tester`**: End-to-end a interakční testování.
9. **`validator-build-test-agent`**: Nativní příkazy repozitáře a verifikace.
10. **`compliance-maintainability-reviewer`**: Konvence kódu a analýza dopadu (blast radius).
11. **`opposition-reviewer`**: Falsifikace hypotéz a detekce leakage.
12. **`acceptance-reviewer-product-qa`**: Produktové QA s přímými důkazy.
13. **`security-reliability-reviewer`**: Bezpečnost a limity důvěry.
14. **`research-experiment-auditor`**: Kvantitativní výzkum, ML governance a OOS validace.
15. **`memory-state-curator`**: Práce s pamětí (Obsidian, Graphify).
16. **`completion-auditor`**: Nezávislý mechanický audit pro 100% uzavření úkolů.
17. **`documentation-handoff-agent`**: Dopad na dokumentaci a finální předání.
18. **`invariant-auditor`**: Audit neměnnosti globálních invariancí.
19. **`report-consistency-auditor`**: Křížová kontrola konzistence výstupů.
20. **`research-validity-auditor`**: Vědecká validace výzkumu.
21. **`semantic-completion-auditor`**: Nezávislý sémantický audit dokončení.

---

## 🚀 Instalace a obnova

### Rychlá automatická instalace (doporučeno)

Spusťte přiložený PowerShell skript v terminálu s oprávněním uživatele:

```powershell
# 1. Základní obnova globálního prostředí (GEMINI.md, skills, plugin)
.\install.ps1

# 2. Nebo obnova včetně nasazení do konkrétního projektu:
.\install.ps1 -TargetRepoPath "C:\Cesta\K\VytvorenemuProjektu"
```

Skript provede:
1. Zálohu stávajícího `~/.gemini/GEMINI.md` na `GEMINI.md.bak` a instalaci nové konfigurace.
2. Zkopírování všech 21 dovedností do `~/.gemini/config/skills/`.
3. Nasazení ASW pluginu do `~/.gemini/config/plugins/antigravity-swarm/`.
4. (Volitelně) Zkopírování `.antigravity/` přímo do kořene vašeho cílového repozitáře.

---

## 📄 Licence

Tento balíček obsahuje otevřené komponenty pod licencí MIT a interní konfigurace koordinátora.
Určeno pro zálohování a správu prostředí Antigravity.
