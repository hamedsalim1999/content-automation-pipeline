# Learning Path — Content Automation Product

Your existing skills are strong: OCI, OKE, Terraform, Helm, ArgoCD, Python, Go, Prometheus/Grafana, PostgreSQL, Redis.
This learning path covers only the **gaps** needed for this specific product.

---

## Stage 1 — LLM & RAG Fundamentals (2-3 weeks)

**Goal**: Understand how LLMs work, how RAG works, and get comfortable calling Ollama locally.

### 1.1 How LLMs work (conceptual, 2 days)
- [ ] Read: [Andrej Karpathy — Intro to Large Language Models (1hr video)](https://www.youtube.com/watch?v=zjkBMFhNj_g)
- [ ] Read: [Illustrated Transformer — Jay Alammar](https://jalammar.github.io/illustrated-transformer/)

**Mini project**: Run `ollama run llama3.1:8b` locally, send it 5 different prompts, observe how temperature changes output.

---

### 1.2 Prompt Engineering (3 days)
- [ ] Read: [Anthropic Prompt Engineering Guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
  (concepts apply to Llama too — system prompts, few-shot, chain-of-thought)
- [ ] Read: [OpenAI Prompt Engineering Guide](https://platform.openai.com/docs/guides/prompt-engineering)

**Mini project**: Write a Python script that takes an article title and returns:
1. A 3-sentence summary
2. 5 related search queries
Use Ollama API (`requests.post` to `localhost:11434/api/chat`)

---

### 1.3 RAG (Retrieval Augmented Generation) (1 week)
- [ ] Watch: [RAG from scratch — LangChain YouTube (12 videos, 10 min each)](https://www.youtube.com/playlist?list=PLfaIDFEXuae2LXbO1_PKyVJiQ23ZztA0x)
- [ ] Read: [Qdrant documentation — Quickstart](https://qdrant.tech/documentation/quick-start/)
- [ ] Read: [nomic-embed-text model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1)

**Mini project**: Build a simple RAG system:
1. Scrape 5 blog posts with `feedparser`
2. Embed them with `sentence-transformers`
3. Store in Qdrant (local Docker)
4. Ask Ollama a question, retrieve relevant chunks first, include in prompt
5. Compare answer quality with/without RAG context

```bash
# Local setup for mini project
docker run -p 6333:6333 qdrant/qdrant
ollama pull llama3.1:8b
pip install sentence-transformers qdrant-client feedparser
```

---

## Stage 2 — Apache Airflow on Kubernetes (1-2 weeks)

**Goal**: You know K8s well. Learn Airflow's DAG model and KubernetesExecutor.

### 2.1 Airflow Core Concepts (3 days)
- [ ] Read: [Airflow Concepts — official docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html)
  Focus on: DAGs, Tasks, XCom, Variables, Connections, TaskFlow API
- [ ] Watch: [Airflow for MLOps — Astronomer (2hr)](https://www.youtube.com/watch?v=K9AnJ9_ZAXE)

**Mini project**: Create a DAG with 3 tasks:
1. Fetch weather data from a public API
2. Process it with Python
3. Print summary to logs
Run it with LocalExecutor first.

---

### 2.2 Airflow on Kubernetes (3 days)
- [ ] Read: [Airflow KubernetesExecutor docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/executor/kubernetes.html)
- [ ] Read: [Official Airflow Helm chart](https://airflow.apache.org/docs/helm-chart/stable/index.html)

**Mini project**: Deploy Airflow on local kind cluster using Helm:
```bash
kind create cluster
helm repo add apache-airflow https://airflow.apache.org
helm install airflow apache-airflow/airflow \
  --set executor=KubernetesExecutor
```
Run your weather DAG on KubernetesExecutor, watch pods spin up and die.

---

### 2.3 Airflow TaskFlow API + XCom (2 days)
- [ ] Read: [TaskFlow API docs](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/taskflow.html)
  This is the `@task` decorator pattern used in `weekly_content_pipeline.py`

**Mini project**: Refactor your weather DAG to use `@task` decorators and pass data between tasks via return values (XCom).

---

## Stage 3 — Ollama on OKE + GPU Nodes (1 week)

**Goal**: You know OKE well. Learn to run Ollama as a K8s service with GPU auto-scaling.

### 3.1 Ollama on Kubernetes (2 days)
- [ ] Read: [Ollama Docker docs](https://hub.docker.com/r/ollama/ollama)
- [ ] Read: [Ollama REST API reference](https://github.com/ollama/ollama/blob/main/docs/api.md)

**Mini project**: Deploy Ollama to your OKE cluster:
```yaml
# Key parts of the Deployment
resources:
  limits:
    nvidia.com/gpu: "1"   # for 70B
# or no GPU limits for 8B (CPU only)
```
Call it from Python using `requests.post`.

---

### 3.2 OKE Cluster Autoscaler for GPU scaling (3 days)
- [ ] Read: [OKE Cluster Autoscaler docs](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengusingclusterautoscaler.htm)
- [ ] Read: [OKE Node Pools with GPU shapes](https://docs.oracle.com/en-us/iaas/Content/ContEng/Reference/contengimagesshapes.htm)

**Mini project**: Create an OKE node pool that:
- Only provisions `VM.GPU.A10.1` nodes
- Has a `nvidia.com/gpu` taint
- Scales to 0 after 5 minutes idle (via Cluster Autoscaler `scale-down-unneeded-time`)
Deploy your Ollama 70B with a GPU toleration and watch the autoscaler provision/deprovision the node.

---

## Stage 4 — OCI Object Storage + SDK (2 days)

**Goal**: Replace S3 calls — learn OCI Object Storage and the Python SDK.

- [ ] Read: [OCI Object Storage docs](https://docs.oracle.com/en-us/iaas/Content/Object/Concepts/objectstorageoverview.htm)
- [ ] Read: [OCI Python SDK — Object Storage](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/object_storage.html)
- [ ] Read: [OCI Instance Principals auth](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm)

**Mini project**: From a Python script running inside OKE (or locally with `~/.oci/config`):
1. Create a bucket
2. Upload a JSON file
3. Download it back and verify the contents

```python
import oci

# In OKE pods — uses workload/instance identity (no config file needed)
signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
object_storage = oci.object_storage.ObjectStorageClient(config={}, signer=signer)

namespace = object_storage.get_namespace().data
object_storage.put_object(
    namespace_name=namespace,
    bucket_name="my-bucket",
    object_name="test.json",
    put_object_body='{"hello": "oracle"}',
    content_type="application/json",
)
```

---

## Stage 5 — Web Scraping & SearXNG (3 days)

### 5.1 RSS + feedparser (1 day)
- [ ] Read: [feedparser docs](https://feedparser.readthedocs.io/en/latest/)

**Mini project**: Script that fetches top 10 articles from 5 Medium RSS feeds, deduplicates by URL, saves to JSON.

---

### 5.2 SearXNG self-hosted (2 days)
- [ ] Read: [SearXNG docs](https://docs.searxng.org/)
- [ ] Read: [SearXNG API reference](https://docs.searxng.org/dev/search_api.html)

**Mini project**: Deploy SearXNG on your local Docker:
```bash
docker run -p 8080:8080 searxng/searxng
```
Write Python function that takes a query, returns top 10 results as list of dicts.

---

## Stage 6 — Text-to-Speech with Kokoro (3 days)

**Goal**: Generate natural-sounding voice from scripts.

- [ ] Read: [Kokoro TTS GitHub](https://github.com/hexgrad/kokoro)
- [ ] Read: [Kokoro FastAPI server](https://github.com/remsky/Kokoro-FastAPI) — this is what you deploy on OKE

**Mini project**: Run Kokoro locally:
```bash
docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:latest
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello from Kokoro TTS", "voice": "af_sky"}' \
  --output test.mp3
```
Generate 3 different voices for the same script. Pick the best one.

---

## Stage 7 — FFmpeg Video Composition (3 days)

**Goal**: Combine AI video + voice audio into final video.

- [ ] Read: [FFmpeg Getting Started](https://ffmpeg.org/getting-started.html)
- [ ] Read: [FFmpeg filters docs](https://ffmpeg.org/ffmpeg-filters.html) — focus on `scale`, `overlay`, `drawtext`

**Mini project**: Given a 10-second video clip and an MP3 file:
1. Loop the video to match audio length
2. Add audio track
3. Resize to 1080x1920 (vertical for Reels/Shorts)
4. Add a text overlay with the article title
```bash
ffmpeg -stream_loop -1 -i video.mp4 -i audio.mp3 \
  -c:v libx264 -c:a aac -shortest \
  -vf "scale=1080:1920,drawtext=text='Your Title':fontsize=48:fontcolor=white:x=50:y=50" \
  output.mp4
```

---

## Stage 8 — Telegram Bot (3 days)

**Goal**: Build the review/approval workflow.

- [ ] Read: [python-telegram-bot docs](https://docs.python-telegram-bot.org/en/stable/)
- [ ] Read: [Telegram Bot API — inline keyboards](https://core.telegram.org/bots/features#inline-keyboards)

**Mini project**: Build a bot that:
1. Receives a `/review` command
2. Sends a sample video with Approve / Edit / Reject inline buttons
3. On Approve: prints "Publishing..."
4. On Edit: asks for a prompt via text reply
5. On Reject: prints "Discarded"

---

## Stage 9 — YouTube + Instagram Publishing (1 week)

### 9.1 YouTube Data API v3 (3 days)
- [ ] Read: [YouTube Data API — Uploading Videos](https://developers.google.com/youtube/v3/guides/uploading_a_video)
- [ ] Read: [google-api-python-client docs](https://googleapis.github.io/google-api-python-client/docs/)

**Mini project**: Upload a test video to YouTube (unlisted) via Python script using OAuth2.

---

### 9.2 Instagram Graph API (3 days)
- [ ] Read: [Instagram Graph API — Reels Publishing](https://developers.facebook.com/docs/instagram-api/guides/reels-publishing)
  Note: requires a Facebook Business account + Instagram Professional account

**Mini project**: Upload a test Reel via the Graph API.

---

## Stage 10 — RunwayML API (2 days)

- [ ] Read: [RunwayML API docs](https://docs.runwayml.com/)
- [ ] Sign up for RunwayML account (pay-per-use, ~$0.05 per second of video)

**Mini project**: Generate a 5-second AI video from a text prompt using the API. Download and inspect the output.

---

## Suggested Order & Timeline

```
Week 1-2:  Stage 1 (LLM + RAG) ← most important foundation
Week 3:    Stage 2 (Airflow on K8s)
Week 4:    Stage 3 (Ollama + OKE GPU autoscaling)
Week 5:    Stage 4 + 5 (OCI Object Storage + Scraping)
Week 6:    Stage 6 + 7 (TTS + FFmpeg)
Week 7:    Stage 8 (Telegram)
Week 8-9:  Stage 9 + 10 (Publishing + RunwayML)
Week 10+:  Build and integrate everything
```

---

## Key Libraries Summary

```
# Core AI
ollama                     # Python client for Ollama
sentence-transformers      # embeddings
qdrant-client              # vector DB client

# Data collection
feedparser                 # RSS
playwright                 # JS-heavy scraping (if needed)
requests                   # HTTP client, SearXNG calls

# Airflow
apache-airflow[kubernetes] # DAG framework

# OCI
oci                        # OCI Python SDK (Object Storage, auth)

# Media
kokoro                     # TTS (or via HTTP to self-hosted server)
ffmpeg-python              # Python wrapper for FFmpeg

# Bots & publishing
python-telegram-bot        # Telegram
google-api-python-client   # YouTube
requests                   # Instagram Graph API
```
