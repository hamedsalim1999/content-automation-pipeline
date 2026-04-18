# Architecture

## Final Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| **Orchestration** | Apache Airflow (Helm on OKE) | KubernetesExecutor — each task = isolated pod |
| **LLM** | Ollama on OKE (Llama 3.1) | 8B on CPU pods, 70B on GPU node via OKE Autoscaler |
| **Embeddings** | sentence-transformers on OKE | `nomic-embed-text`, CPU only |
| **Vector DB** | Qdrant (Helm on OKE) | StatefulSet + PVC |
| **Queue** | Redis Streams | Airflow state + inter-service events |
| **Database** | PostgreSQL (OCI Database Service) | Pipeline metadata, content state |
| **Object Storage** | OCI Object Storage | Articles, audio, video files |
| **Web Research** | SearXNG (self-hosted on OKE) | Open source metasearch, replaces Tavily |
| **TTS** | Kokoro TTS (self-hosted on OKE) | Best open source TTS quality |
| **Video Compose** | FFmpeg | Audio + visuals composition |
| **AI Video** | RunwayML API | Only external paid dependency |
| **Scraping** | RSS (feedparser) + Playwright | Free, no API key |
| **Telegram** | python-telegram-bot | Review + approval workflow |
| **Publishing** | YouTube Data API + Instagram Graph API | Free |
| **CI/CD** | GitLab CI + ArgoCD | Your current stack |
| **Monitoring** | Prometheus + Grafana + Loki | Your current stack |

---

## Full System Architecture

```mermaid
graph TB
    subgraph "Trigger"
        CRON[Airflow Weekly CronJob]
    end

    subgraph "Data Collection"
        MS[Medium Scraper<br/>RSS + feedparser]
        SEARXNG[SearXNG<br/>Self-hosted metasearch]
    end

    subgraph "AI Layer - Ollama on OKE"
        OLLAMA_8B[Ollama Llama 3.1 8B<br/>CPU node<br/>fact-check / scripts / classify]
        OLLAMA_70B[Ollama Llama 3.1 70B<br/>GPU node via OKE Autoscaler<br/>article generation]
        EMBED[sentence-transformers<br/>nomic-embed-text<br/>CPU node]
    end

    subgraph "Storage"
        OCI_OBJ[(OCI Object Storage<br/>articles / audio / video)]
        QDRANT[(Qdrant<br/>Vector DB)]
        PG[(PostgreSQL<br/>OCI DB Service)]
        REDIS[(Redis<br/>streams + cache)]
    end

    subgraph "Media Production"
        KOKORO[Kokoro TTS<br/>self-hosted on OKE]
        FFMPEG[FFmpeg composer<br/>audio + visuals]
        RUNWAY[RunwayML API<br/>AI video generation]
    end

    subgraph "Review & Publish"
        TELEGRAM[Telegram Bot]
        YOUTUBE[YouTube Data API]
        INSTAGRAM[Instagram Graph API]
    end

    CRON --> MS
    MS --> OCI_OBJ
    MS --> SEARXNG
    SEARXNG --> EMBED
    EMBED --> QDRANT
    QDRANT --> OLLAMA_70B
    OLLAMA_70B --> OCI_OBJ
    OCI_OBJ --> OLLAMA_8B
    OLLAMA_8B --> OCI_OBJ
    OCI_OBJ --> KOKORO
    KOKORO --> OCI_OBJ
    OCI_OBJ --> RUNWAY
    RUNWAY --> OCI_OBJ
    OCI_OBJ --> FFMPEG
    FFMPEG --> OCI_OBJ
    OCI_OBJ --> TELEGRAM
    TELEGRAM --> |Approve| YOUTUBE
    TELEGRAM --> |Approve| INSTAGRAM
    TELEGRAM --> |Edit| OLLAMA_70B
```

---

## Airflow DAG — Weekly Pipeline

```mermaid
graph LR
    A[scrape_medium] --> B[research_topics]
    B --> C[embed_and_store]
    C --> D[generate_article<br/>Llama 3.1 70B]
    D --> E[fact_check<br/>Llama 3.1 8B]
    E --> F{passed?}
    F -->|yes| G[generate_video_script<br/>Llama 3.1 8B]
    F -->|no - apply corrections| D
    G --> H[synthesize_voice<br/>Kokoro TTS]
    G --> I[generate_ai_video<br/>RunwayML]
    H --> J[compose_video<br/>FFmpeg]
    I --> J
    J --> K[notify_telegram]
    K --> L{human decision}
    L -->|approve| M[publish]
    L -->|edit prompt| D
    M --> N[youtube_upload]
    M --> O[instagram_upload]
```

---

## Kubernetes Layout on OKE

```
OCI OKE Cluster
│
├── Namespace: airflow
│   ├── Scheduler (Deployment)
│   ├── Webserver (Deployment)
│   └── Workers (KubernetesExecutor — pod per task, auto cleanup)
│
├── Namespace: ai
│   ├── ollama-8b   (Deployment — CPU node, always on)
│   ├── ollama-70b  (Deployment — GPU node, OKE Autoscaler scales to 0 when idle)
│   ├── embeddings  (Deployment — CPU node, always on)
│   ├── kokoro-tts  (Deployment — CPU node)
│   └── searxng     (Deployment — CPU node)
│
├── Namespace: data
│   ├── qdrant      (StatefulSet + PVC — 3 replicas)
│   └── redis       (StatefulSet + PVC)
│
├── Namespace: bots
│   └── telegram-bot (Deployment — always on, listens for messages)
│
└── Namespace: monitoring
    ├── prometheus
    ├── grafana
    └── loki
```

---

## Ollama on OKE — Node Strategy

```
CPU Node Pool (always running — VM.Standard.E4.Flex 4 OCPU ~$0.10/hr)
  └── ollama-8b, embeddings, kokoro-tts, searxng, airflow

GPU Node Pool (OKE Cluster Autoscaler — scales to 0 when idle)
  └── ollama-70b on VM.GPU.A10.1 (~$0.45/hr)
      Active only during article generation (~30 min/week)
      Estimated GPU cost: ~$0.22/week
```

---

## Data Flow in OCI Object Storage

```
oci://your-bucket/YYYY-WW/
  ├── raw/          ← scraped Medium articles (JSON)
  ├── research/     ← SearXNG results per topic (JSON)
  ├── articles/     ← generated + fact-checked article (JSON + MD)
  ├── audio/        ← Kokoro TTS output (MP3)
  ├── video/raw/    ← RunwayML AI clips (MP4)
  └── video/final/  ← FFmpeg composed final video (MP4)
```

---

## GitOps Flow (same as your Sinch pattern)

```
git push to GitLab
      │
      ▼
GitLab CI: lint → test → docker build → push to OCIR → update Helm values
      │
      ▼
ArgoCD detects Helm values change → deploy to OKE
```
