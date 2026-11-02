# MindScape Island (潮汐岛)

A seven-day social simulation for exploring personality assessment through conversation and gameplay. Players meet residents, visit island locations, join activities, and create objects. The study pairs an island observation report with the Chinese Big Five Inventory–2 (BFI-2) questionnaire and collects feedback on both.

Weitian Xue · Duke Kunshan University · Mentor: Yucheng Jin

## Try the reviewer demo

Visit the [reviewer demo](https://review.mychaoxidao.com/review) and enter the shared access code `MindScape-GFWWTXZUGUF5`. Choose a nickname, accept the experience notice, and start playing. The code can be reused, and each browser keeps separate saves. You can resume a previous visit or start a new one without deleting earlier progress or reports. Save your personal recovery code to restore your records on another device or after clearing browser data. Reviewer records are stored separately and excluded from the research dataset.

## Source version

The core game corresponds to the formal-study deployment of 26 October 2026: world `chaoxi-holiday-v6`, experience `island-life-20261026-v1`. This repository also includes the independent reviewer entry deployed on 2 November 2026. Contact details have been replaced with placeholders and comments shortened; gameplay, prompts, scoring, and artwork retain the deployed implementation.

The assessment integrity check includes source comments. This copy therefore uses a new fingerprint, recorded alongside the production fingerprint in `RELEASE.json`. Existing production reports remain bound to their original version.

## Structure

```text
backend/
  agents/      Dialogue, model transport, and response checks
  assets/      Island artwork
  content/     World packs and activity content
  data/        Static world data
  services/    Simulation, activities, and persistence
  study/       Study workflow, instruments, and reports
  world/       World definitions and rules
  main.py      FastAPI application
frontend/
  app/         Next.js routes and study pages
  components/  Game and study interfaces
  hooks/       Shared React hooks
  lib/         Client and server utilities
  public/      Static resources
deploy/        Container recipes and example configuration
scripts/       File integrity check
```

## Run

The container recipes use Python 3.13, Node.js 22, and locked dependencies. From the repository root:

```sh
cp deploy/server.env.example deploy/server.env
```

Set `STUDY_PUBLIC_ORIGIN`, `LLM_API_KEY`, and `STUDY_CONTACT_ENCRYPTION_KEY` in `deploy/server.env`. The contact key must be a Fernet key; generate it in a Python environment with `cryptography` installed:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then start the stack:

```sh
docker compose --env-file deploy/server.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/server.env -f deploy/compose.yaml up -d --build
```

The gateway listens on `127.0.0.1:8080`. Configure an HTTPS reverse proxy at `STUDY_PUBLIC_ORIGIN` and open `/study/start`. The model configuration preserves the study's Qwen endpoint and model name; it requires a compatible service account. Use a fresh database and encryption key for a separate installation.

Invitations are managed by `python -m study.admin --help` from `backend/`, with an explicit `DATABASE_URL`. No formal-study invitation codes, private credentials, participant records, or databases are included. Consent contacts are placeholders and must be replaced before any new study.

## Verify

```sh
python scripts/verify_release.py --strict
```

Run this before building: Next.js can regenerate `next-env.d.ts`. `.gitattributes` preserves line endings used in source hashing. Backend content and assessment checks, after installing `backend/requirements.lock`, run from `backend/`:

```sh
python -m content.validator --pack content/packs/chaoxi_holiday_v6
python -m study.production_letter
```

The development test suite is not included in this deployment snapshot; the retained `test:e2e` npm entries require that suite.

## Rights and sources

No project-wide open-source license is granted. Third-party terms remain applicable; notices for adapted dialogue materials are in [NOTICE](NOTICE).

BFI-2 is copyrighted by Christopher J. Soto and Oliver P. John and is available for noncommercial research under its [official terms](https://www.ocf.berkeley.edu/~johnlab/bfi.html). Chinese wording follows Zhang et al. (2022), *The Big Five Inventory-2 in China*, *Assessment*, 29(6), 1262–1284. Questionnaire materials remain subject to their authors' terms; this repository grants no additional rights to them. Reading excerpts retain source attributions in the content modules.

## Acknowledgments

Thanks to Yucheng Jin, the study participants, and Jerry Zheng for game-design ideas and inspiration.

## Reviewer entry

The optional reviewer entry at `/review` uses a reusable admission passphrase and separate browser accounts. Each account can retain several visits, resume progress, or recover its history with a personal recovery code. Reviewer data must use its own `reviewer.sqlite` database and volumes; never mount the research database into this service.

Set `REVIEW_MODE=true` in both services. The backend also requires `REVIEW_ACCESS_CODE_SHA256` (the SHA-256 digest of the admission passphrase) and a random `REVIEW_SIGNING_SECRET` of at least 32 characters. Keep that signing secret stable so existing recovery codes continue to work. The isolated deployment is defined in `deploy/compose.review.yaml`; its review Dockerfiles extend the tagged formal-release images and preserve the gameplay assets. Credentials belong in an untracked `deploy/review.env`.
