# AI Content Automation Pipeline

End-to-end weekly pipeline: **Medium → Research → RAG Article → Fact Check → AI Video → Telegram Review → YouTube/Instagram**

---

## Pipeline Flow

```
[Airflow Weekly DAG — every Monday 08:00]
        │
        ▼
[Medium RSS Scraper]       feedparser — top 10 articles
        │
        ▼
[Topic Researcher]         SearXNG (self-hosted) — deep web search
        │
        ▼
[Embed + Store]            sentence-transformers → Qdrant
        │
        ▼
[Article Generator]        RAG + Llama 3.1 70B on GPU node
        │
        ▼
[Fact Checker]             Llama 3.1 8B + SearXNG evidence
        │
        ▼
[Video Script Generator]   Llama 3.1 8B — short + long scripts
        │
        ├──────────────────────────────┐
        ▼                              ▼
[Voice Synthesis]          [AI Video Generation]
 Kokoro TTS (self-hosted)   RunwayML API
        │                              │
        └──────────────┬───────────────┘
                       ▼
              [FFmpeg Composer]
                       │
                       ▼
              [Telegram Bot]      — send sample for review
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          APPROVE               EDIT
             │                   │
             ▼                   └── new prompt → Article Generator
      [Publisher]
     ┌────────┴────────┐
     ▼                 ▼
  YouTube          Instagram
(long video)      (short reel)
```

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| **Orchestration** | Apache Airflow (Helm on EKS, KubernetesExecutor) |
| **LLM** | Ollama — Llama 3.1 70B (GPU) + 8B (CPU) |
| **Embeddings** | sentence-transformers `nomic-embed-text` (CPU) |
| **Vector DB** | Qdrant (StatefulSet on EKS) |
| **Web Research** | SearXNG self-hosted on EKS |
| **TTS** | Kokoro TTS self-hosted on EKS |
| **AI Video** | RunwayML API |
| **Video Compose** | FFmpeg |
| **Review** | Telegram Bot (python-telegram-bot) |
| **Publishing** | YouTube Data API v3 + Instagram Graph API |
| **Storage** | AWS S3 |
| **Database** | PostgreSQL (AWS RDS) + Redis |
| **CI/CD** | GitLab CI + ArgoCD |
| **Monitoring** | Prometheus + Grafana + Loki |
| **Infrastructure** | AWS EKS + Terraform + Helm + Karpenter |

---

## Repository Structure

```text
.
├── README.md
├── ARCHITECTURE.md          # Full architecture + Mermaid diagrams
├── dags/
│   └── weekly_content_pipeline.py   # Airflow DAG — full pipeline
└── learning-path/
    └── LEARNING_PATH.md     # Staged learning path with mini-projects
```

---

## EKS Namespace Layout

```text
airflow/      Scheduler, Webserver, KubernetesExecutor workers
ai/           ollama-8b (CPU), ollama-70b (GPU/Karpenter), embeddings, kokoro-tts, searxng
data/         qdrant (StatefulSet), redis (StatefulSet)
bots/         telegram-bot (always-on Deployment)
monitoring/   prometheus, grafana, loki
```

---

## Estimated Weekly Cost (personal project)

| Resource | Cost |
| --- | --- |
| EKS cluster (t3.xlarge CPU nodes) | ~$120/month |
| GPU node g4dn.xlarge ~30min/week | ~$1/month |
| RDS PostgreSQL db.t3.micro | ~$15/month |
| S3 storage | ~$1/month |
| RunwayML (~10 sec video/week) | ~$2/month |
| **Total** | **~$140/month** |
