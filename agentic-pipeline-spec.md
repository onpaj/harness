# Agentic Development Pipeline — Specifikace

## Přehled

Distribuovaný, event-driven systém pro autonomní zpracování development tasků pomocí specializovaných AI agentů. Uživatel zadá pouze požadavek (feature brief), zbytek pipeline zpracují agenti bez nutnosti lidského zásahu.

---

## Cíle

- Plně autonomní pipeline od zadání po code review
- Distribuce zpracování přes více strojů (lokál + remote)
- Reaktivní architektura bez pollingu (vyjma Storage Queue 1s interval)
- Definice agentů jako verzovatelné Markdown soubory
- Volba LLM modelu per typ agenta
- Fault tolerance bez externího orchestračního agenta

---

## Technologický stack

| Komponenta | Technologie |
|---|---|
| Message queues | Azure Storage Queues |
| Artifact store | Azure Blob Storage |
| Agent runtime | Claude Code CLI (`claude --print`) |
| Agent definice | Markdown + YAML frontmatter |
| Worker process | Bash / Node.js skript |
| Infrastruktura | Stávající Azure (M365 tenant) |

---

## Architektura

### Queues (jedna per fáze)

```
planner-queue
architect-queue
designer-queue
developer-queue
review-queue
```

Každá queue obsluhuje jeden typ agenta. Více workerů může konzumovat stejnou queue paralelně (load balancing přes visibility timeout).

### Artifact store

Azure Blob Storage container `pipeline-artifacts`. Struktura:

```
artifacts/
  {feature-id}/
    brief.md           ← vstup od uživatele
    spec.md            ← výstup planner agenta
    arch-review.md     ← výstup architect agenta
    design.md          ← výstup designer agenta
    impl/{task}.md     ← výstupy developer agentů
    review.md          ← výstup review agenta
```

---

## Task message formát

Každá zpráva ve frontě obsahuje:

```json
{
  "feature_id": "feat-42",
  "task_id": "feat-42-arch-1",
  "input_artifacts": [
    "artifacts/feat-42/brief.md",
    "artifacts/feat-42/spec.md"
  ],
  "output_artifact": "artifacts/feat-42/arch-review.md",
  "next_queue": "designer-queue",
  "context": "Volitelný doplňující kontext pro agenta"
}
```

---

## Agent definice

Agenti jsou definováni jako Markdown soubory s YAML frontmatter, uložené v `.agents/` ve version control.

```
.agents/
  planner.md
  architect.md
  designer.md
  developer.md
  reviewer.md
```

### Frontmatter schéma

```yaml
---
id: architect
model: claude-opus-4-6
phase: architect
max_turns: 20
tools:
  - read
  - write
  - bash
---
```

Tělo souboru obsahuje system prompt agenta včetně instrukcí pro formát outputu a kdy ukončit session.

---

## Agenti a jejich role

### Planner
- **Model:** claude-opus-4-6
- **Input:** brief.md (zadání od uživatele)
- **Output:** spec.md — strukturovaná specifikace featury
- **Next queue:** architect-queue

### Architect
- **Model:** claude-opus-4-6
- **Input:** brief.md, spec.md
- **Output:** arch-review.md — posouzení fit do stávající architektury projektu, případné úpravy specifikace
- **Next queue:** designer-queue

### Designer
- **Model:** claude-sonnet-4-6
- **Input:** spec.md, arch-review.md
- **Output:** design.md — UX/UI požadavky, komponenty, flow
- **Next queue:** developer-queue (může generovat více tasků = více zpráv)

### Developer
- **Model:** claude-sonnet-4-6
- **Input:** spec.md, arch-review.md, design.md + konkrétní task
- **Output:** impl/{task}.md (shrnutí) + kód zapsaný přímo do pracovního adresáře
- **GitHub backend:** po dokončení jsou všechny změny v pracovním adresáři automaticky commitnuty a pushnuty do feature branche (`git add -A → commit → push`) před uploadem impl artefaktu
- **Next queue:** review-queue (po dokončení všech developer tasků pro danou feature)

### Reviewer
- **Model:** claude-haiku-4-5-20251001
- **Input:** spec.md, arch-review.md + všechny impl výstupy
- **Output:** review.md — code review, shoda se specifikací, formální kontrola
- **Next queue:** — (konec pipeline, nebo zpět do developer-queue při nalezení problémů)

---

## Worker lifecycle

Každý worker proces (bash nebo Node.js) běží kontinuálně na daném stroji:

1. Pokus o přijetí zprávy z příslušné queue
2. Pokud žádná zpráva → sleep 1s → opakuj
3. Zpráva přijata → visibility timeout aktivní (agent má čas na zpracování)
4. Stažení input artifacts z Blob Storage
5. Sestavení promptu z agent MD souboru + artifacts
6. Spuštění `claude --model {model} --print -p "{prompt}"`
7. (GitHub backend, developer agent) Commit všech souborů zapsaných agentem do feature branche (`git add -A → commit → push`)
8. Upload output artifact (impl markdown / review) do storage backendu
9. Publikace zprávy do next queue
10. Smazání zpracované zprávy z aktuální queue

Pokud worker selže mezi kroky 3–10, zpráva se automaticky vrátí do queue po vypršení visibility timeout.

---

## Distribuce

Worker procesy mohou běžet na libovolném stroji s přístupem k Azure Storage (přes standardní Azure credentials nebo connection string). Lokální i remote stroje sdílí stejné queues a artifact store — koordinace je zajištěna visibility timeout mechanismem bez nutnosti přímé komunikace mezi stroji.

```
[Azure Storage Queues + Blob Storage]
        ↑↓                    ↑↓
[Lokál: planner, architect]   [Remote: developer workers ×N]
```

---

## Fault tolerance

- **Worker crash:** zpráva se vrátí do queue po vypršení visibility timeout
- **Partial output:** artifact se uploaduje až po úspěšném dokončení agenta
- **Retry logika:** zpráva má counter pokusů (Azure Storage Queues built-in `dequeueCount`), po N selháních přesun do dead-letter queue
- **Dead-letter queue:** `{queue-name}-poison` — manuální inspekce

---

## Paralelismus

- **Developer fáze:** Designer agent může publikovat více zpráv do developer-queue → developer workeři je zpracují paralelně
- **Wait for all:** Review agent se spouští až po dokončení všech developer tasků pro danou feature — koordinace přes `pending_tasks` counter v task message nebo dedikovaný blob `artifacts/{feature-id}/state.json`

---

## Spuštění pipeline

Jediný manuální krok — publikace počáteční zprávy do planner-queue:

```bash
az storage message put \
  --queue-name planner-queue \
  --content "$(echo '{
    "feature_id": "feat-42",
    "task_id": "feat-42-plan-1",
    "input_artifacts": ["artifacts/feat-42/brief.md"],
    "output_artifact": "artifacts/feat-42/spec.md",
    "next_queue": "architect-queue"
  }' | base64)"
```

Brief (zadání) musí být předem nahrán do Blob Storage.

---

## Konfigurace

```
.agents/           ← definice agentů (version control)
.pipeline/
  config.json      ← mapování queue → agent soubor, timeout hodnoty
```

### config.json

```json
{
  "queues": {
    "planner-queue":   { "agent": ".agents/planner.md",   "visibility_timeout": 300 },
    "architect-queue": { "agent": ".agents/architect.md", "visibility_timeout": 600 },
    "designer-queue":  { "agent": ".agents/designer.md",  "visibility_timeout": 300 },
    "developer-queue": { "agent": ".agents/developer.md", "visibility_timeout": 1800 },
    "review-queue":    { "agent": ".agents/reviewer.md",  "visibility_timeout": 600 }
  },
  "storage": {
    "account": "your-storage-account",
    "container": "pipeline-artifacts"
  },
  "dead_letter_threshold": 3
}
```

---

## Co není součástí specifikace

- Konkrétní system prompty agentů (doménově specifické, iterovat dle výsledků)
- UI pro monitoring pipeline stavu
- Integrace s GitHub/Azure DevOps (PR creation, branch management)
- Autentizace a autorizace přístupu k pipeline
