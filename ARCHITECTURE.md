# Architecture

## Final Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| **Orchestration** | Apache Airflow (Helm on EKS) | KubernetesExecutor — each task = isolated pod |
| **LLM** | Ollama on EKS (Llama 3.1) | 8B on CPU pods, 70B on GPU node via Karpenter |
| **Embeddings** | sentence-transformers on EKS | `nomic-embed-text`, CPU only |
| **Vector DB** | Qdrant (Helm on EKS) | StatefulSet + PVC |
| **Queue** | Redis Streams | Airflow state + inter-service events |
| **Database** | PostgreSQL (AWS RDS) | Pipeline metadata, content state |
| **Object Storage** | AWS S3 | Articles, audio, video files |
| **Web Research** | SearXNG (self-hosted on EKS) | Open source metasearch, replaces Tavily |
| **TTS** | Kokoro TTS (self-hosted on EKS) | Best open source TTS quality |
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

    subgraph "AI Layer - Ollama on EKS"
        OLLAMA_8B[Ollama Llama 3.1 8B<br/>CPU node<br/>fact-check / scripts / classify]
        OLLAMA_70B[Ollama Llama 3.1 70B<br/>GPU node via Karpenter<br/>article generation]
        EMBED[sentence-transformers<br/>nomic-embed-text<br/>CPU node]
    end

    subgraph "Storage"
        S3[(AWS S3<br/>articles / audio / video)]
        QDRANT[(Qdrant<br/>Vector DB)]
        PG[(PostgreSQL RDS<br/>pipeline state)]
        REDIS[(Redis<br/>streams + cache)]
    end

    subgraph "Media Production"
        KOKORO[Kokoro TTS<br/>self-hosted on EKS]
        FFMPEG[FFmpeg composer<br/>audio + visuals]
        RUNWAY[RunwayML API<br/>AI video generation]
    end

    subgraph "Review & Publish"
        TELEGRAM[Telegram Bot]
        YOUTUBE[YouTube Data API]
        INSTAGRAM[Instagram Graph API]
    end

    CRON --> MS
    MS --> S3
    MS --> SEARXNG
    SEARXNG --> EMBED
    EMBED --> QDRANT
    QDRANT --> OLLAMA_70B
    OLLAMA_70B --> S3
    S3 --> OLLAMA_8B
    OLLAMA_8B --> S3
    S3 --> KOKORO
    KOKORO --> S3
    S3 --> RUNWAY
    RUNWAY --> S3
    S3 --> FFMPEG
    FFMPEG --> S3
    S3 --> TELEGRAM
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

## Kubernetes Layout on EKS

```
AWS EKS Cluster
│
├── Namespace: airflow
│   ├── Scheduler (Deployment)
│   ├── Webserver (Deployment)
│   └── Workers (KubernetesExecutor — pod per task, auto cleanup)
│
├── Namespace: ai
│   ├── ollama-8b   (Deployment — CPU node, always on)
│   ├── ollama-70b  (Deployment — GPU node, Karpenter scales to 0 when idle)
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

## Ollama on EKS — Node Strategy

```
CPU Node Pool (always running — t3.xlarge ~$0.17/hr)
  └── ollama-8b, embeddings, kokoro-tts, searxng, airflow

GPU Node Pool (Karpenter — scales to 0 when idle)
  └── ollama-70b on g4dn.xlarge (~$0.52/hr)
      Active only during article generation (~30 min/week)
      Estimated GPU cost: ~$0.26/week
```

---

## Data Flow in S3

```
s3://your-bucket/YYYY-WW/
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
GitLab CI: lint → test → docker build → push to ECR → update Helm values
      │
      ▼
ArgoCD detects Helm values change → deploy to EKS
```
