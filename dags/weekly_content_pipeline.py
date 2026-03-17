"""
Weekly Content Automation Pipeline

Flow:
  scrape_medium
      └── research_topics (parallel per topic)
              └── embed_and_store
                      └── generate_article (Llama 3.1 70B - GPU)
                              └── fact_check (Llama 3.1 8B - CPU)
                                      └── generate_video_script (Llama 3.1 8B)
                                              ├── synthesize_voice (Kokoro TTS)
                                              └── generate_ai_video (RunwayML)
                                                      └── compose_video (FFmpeg)
                                                              └── notify_telegram
                                                                      └── [human approval]
                                                                              └── publish
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable
from airflow.operators.python import BranchPythonOperator

# ── Ollama endpoints (internal K8s services) ─────────────────────────────────
OLLAMA_70B_URL = "http://ollama-70b.ai.svc.cluster.local:11434"   # GPU node
OLLAMA_8B_URL  = "http://ollama-8b.ai.svc.cluster.local:11434"    # CPU node

# ── Other internal services ───────────────────────────────────────────────────
QDRANT_URL     = "http://qdrant.data.svc.cluster.local:6333"
SEARXNG_URL    = "http://searxng.ai.svc.cluster.local:8080"
KOKORO_URL     = "http://kokoro-tts.ai.svc.cluster.local:8880"

# ── AWS / external ────────────────────────────────────────────────────────────
S3_BUCKET      = Variable.get("S3_BUCKET", default_var="content-automation")
RUNWAY_API_KEY = Variable.get("RUNWAY_API_KEY")
TELEGRAM_TOKEN = Variable.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = Variable.get("TELEGRAM_CHAT_ID")


default_args = {
    "owner": "hamed",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=2),
}

with DAG(
    dag_id="weekly_content_pipeline",
    description="Medium scrape → RAG article → fact check → AI video → Telegram review → publish",
    schedule="0 8 * * 1",          # Every Monday 08:00
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["content", "weekly", "llm", "video"],
) as dag:

    # ── TASK 1: Scrape top 10 Medium articles ─────────────────────────────────
    @task(
        task_id="scrape_medium",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "256Mi",
                "request_cpu": "100m",
            }
        },
    )
    def scrape_medium(**context) -> list[dict]:
        """
        Fetch top 10 articles from Medium RSS feeds.
        Returns list of: {title, url, content, tags, published}
        Saves raw JSON to S3: YYYY-WW/raw/articles.json
        """
        import feedparser
        import boto3
        import json
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        # Medium topic RSS feeds to monitor
        feeds = [
            "https://medium.com/feed/tag/devops",
            "https://medium.com/feed/tag/kubernetes",
            "https://medium.com/feed/tag/platform-engineering",
            "https://medium.com/feed/tag/mlops",
            "https://medium.com/feed/tag/cloud-native",
        ]

        articles = []
        for url in feeds:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:  # top 2 per feed = 10 total
                articles.append({
                    "title": entry.title,
                    "url": entry.link,
                    "summary": entry.get("summary", ""),
                    "tags": [t.term for t in entry.get("tags", [])],
                    "published": str(entry.get("published", "")),
                    "source_feed": url,
                })

        # Save to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/raw/articles.json",
            Body=json.dumps(articles, indent=2),
            ContentType="application/json",
        )

        return articles  # XCom to next task


    # ── TASK 2: Research topics via SearXNG ───────────────────────────────────
    @task(
        task_id="research_topics",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "512Mi",
                "request_cpu": "200m",
            }
        },
    )
    def research_topics(articles: list[dict], **context) -> list[dict]:
        """
        For each article, use Ollama 8B to extract the core topic,
        then SearXNG to deep-search that topic.
        Returns enriched research docs.
        """
        import requests
        import json
        import boto3
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")
        research_results = []

        for article in articles:
            # Ask Llama 8B: what is the core topic of this article?
            topic_response = requests.post(
                f"{OLLAMA_8B_URL}/api/chat",
                json={
                    "model": "llama3.1:8b",
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Extract the single most important technical topic from this article title.\n"
                                f"Return only the topic as a short search query (max 5 words).\n\n"
                                f"Title: {article['title']}"
                            ),
                        }
                    ],
                    "stream": False,
                },
                timeout=60,
            )
            topic = topic_response.json()["message"]["content"].strip()

            # SearXNG deep search
            search_response = requests.get(
                f"{SEARXNG_URL}/search",
                params={"q": topic, "format": "json", "categories": "general,it"},
                timeout=30,
            )
            search_data = search_response.json()

            research_results.append({
                "original_article": article,
                "extracted_topic": topic,
                "search_results": search_data.get("results", [])[:10],
            })

        # Save to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/research/results.json",
            Body=json.dumps(research_results, indent=2),
            ContentType="application/json",
        )

        return research_results


    # ── TASK 3: Embed and store in Qdrant ─────────────────────────────────────
    @task(
        task_id="embed_and_store",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "1Gi",
                "request_cpu": "500m",
            }
        },
    )
    def embed_and_store(research_results: list[dict], **context) -> str:
        """
        Embed all research content using sentence-transformers
        and store in Qdrant. Returns the collection name for RAG.
        """
        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
        from datetime import datetime
        import uuid

        week = datetime.now().strftime("%Y-%W")
        collection_name = f"content_{week.replace('-', '_')}"

        model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
        client = QdrantClient(url=QDRANT_URL)

        # Create collection
        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )

        points = []
        for item in research_results:
            # Embed article summary
            texts = [item["original_article"]["summary"]]
            # Embed each search result snippet
            for result in item["search_results"]:
                texts.append(result.get("content", result.get("title", "")))

            embeddings = model.encode(texts, show_progress_bar=False)

            for text, vector in zip(texts, embeddings):
                points.append(
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector.tolist(),
                        payload={
                            "text": text,
                            "topic": item["extracted_topic"],
                            "week": week,
                        },
                    )
                )

        client.upsert(collection_name=collection_name, points=points)
        return collection_name


    # ── TASK 4: Generate article via RAG + Llama 3.1 70B ──────────────────────
    @task(
        task_id="generate_article",
        executor_config={
            "KubernetesExecutor": {
                # This task runs on the GPU node
                "request_memory": "2Gi",
                "request_cpu": "1000m",
                "node_selector": {"workload": "gpu"},
                "tolerations": [
                    {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}
                ],
            }
        },
    )
    def generate_article(collection_name: str, **context) -> dict:
        """
        RAG: retrieve context from Qdrant, generate long-form article
        using Llama 3.1 70B on GPU node.
        """
        import requests
        import boto3
        import json
        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        # Retrieve top context from Qdrant
        model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
        qdrant = QdrantClient(url=QDRANT_URL)

        query = "latest trends and insights in DevOps, Kubernetes, and platform engineering"
        query_vector = model.encode([query])[0].tolist()

        results = qdrant.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=15,
        )
        context_text = "\n\n".join([r.payload["text"] for r in results])

        # Generate article with 70B
        response = requests.post(
            f"{OLLAMA_70B_URL}/api/chat",
            json={
                "model": "llama3.1:70b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior DevOps engineer and technical writer. "
                            "Write clear, practical, and insightful articles for engineers."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Based on the following research context from this week's top Medium articles,\n"
                            f"write a comprehensive technical article (800-1200 words) covering the most\n"
                            f"important insights and trends.\n\n"
                            f"Context:\n{context_text}\n\n"
                            f"Format: markdown with clear sections, code examples where relevant."
                        ),
                    },
                ],
                "stream": False,
                "options": {"num_predict": 2000, "temperature": 0.7},
            },
            timeout=600,  # 70B can be slow
        )

        article_content = response.json()["message"]["content"]

        article = {
            "week": week,
            "content": article_content,
            "collection_name": collection_name,
        }

        # Save to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/articles/draft.json",
            Body=json.dumps(article, indent=2),
            ContentType="application/json",
        )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/articles/draft.md",
            Body=article_content,
            ContentType="text/markdown",
        )

        return article


    # ── TASK 5: Fact check with Llama 3.1 8B ──────────────────────────────────
    @task(
        task_id="fact_check",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "512Mi",
                "request_cpu": "200m",
            }
        },
    )
    def fact_check(article: dict, **context) -> dict:
        """
        Split article into claims, verify each against SearXNG,
        use Llama 3.1 8B to judge accuracy. Returns corrected article.
        """
        import requests
        import boto3
        import json
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        # Ask 8B to extract factual claims from the article
        claims_response = requests.post(
            f"{OLLAMA_8B_URL}/api/chat",
            json={
                "model": "llama3.1:8b",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Extract up to 10 specific factual claims from this article that can be verified.\n"
                            f"Return as JSON array of strings.\n\n"
                            f"Article:\n{article['content'][:3000]}"
                        ),
                    }
                ],
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=120,
        )

        try:
            claims_text = claims_response.json()["message"]["content"]
            # Extract JSON from response
            start = claims_text.find("[")
            end = claims_text.rfind("]") + 1
            claims = json.loads(claims_text[start:end])
        except Exception:
            claims = []

        # Verify each claim via SearXNG + 8B judgment
        issues = []
        for claim in claims[:10]:
            search = requests.get(
                f"{SEARXNG_URL}/search",
                params={"q": claim, "format": "json"},
                timeout=15,
            )
            evidence = " ".join(
                [r.get("content", "") for r in search.json().get("results", [])[:3]]
            )

            verdict_response = requests.post(
                f"{OLLAMA_8B_URL}/api/chat",
                json={
                    "model": "llama3.1:8b",
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Claim: {claim}\n\n"
                                f"Evidence from web: {evidence[:1000]}\n\n"
                                f"Is the claim accurate? Reply with: ACCURATE, INACCURATE, or UNCERTAIN. "
                                f"Then one sentence explanation."
                            ),
                        }
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=60,
            )
            verdict = verdict_response.json()["message"]["content"]
            if "INACCURATE" in verdict:
                issues.append({"claim": claim, "verdict": verdict})

        article["fact_check_issues"] = issues
        article["fact_check_passed"] = len(issues) == 0

        # Save fact-check report to S3
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/articles/fact_check_report.json",
            Body=json.dumps({"issues": issues, "passed": article["fact_check_passed"]}, indent=2),
            ContentType="application/json",
        )

        return article


    # ── TASK 6: Generate video script ─────────────────────────────────────────
    @task(
        task_id="generate_video_script",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "512Mi",
                "request_cpu": "200m",
            }
        },
    )
    def generate_video_script(article: dict, **context) -> dict:
        """
        Summarize article into a 60-90 second video script (short)
        and a 5-7 minute script (long) using Llama 3.1 8B.
        """
        import requests
        import boto3
        import json
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        response = requests.post(
            f"{OLLAMA_8B_URL}/api/chat",
            json={
                "model": "llama3.1:8b",
                "messages": [
                    {
                        "role": "system",
                        "content": "You write engaging video scripts for technical YouTube/Instagram content.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Based on this article, write TWO scripts:\n\n"
                            f"1. SHORT (60-90 seconds for Instagram Reels/YouTube Shorts)\n"
                            f"   - Hook in first 3 seconds\n"
                            f"   - Key insight\n"
                            f"   - Call to action\n\n"
                            f"2. LONG (5-7 minutes for YouTube)\n"
                            f"   - Intro with hook\n"
                            f"   - 3 main points with examples\n"
                            f"   - Conclusion + CTA\n\n"
                            f"Article:\n{article['content'][:2000]}\n\n"
                            f"Return as JSON: {{\"short\": \"...\", \"long\": \"...\"}}"
                        ),
                    },
                ],
                "stream": False,
                "options": {"temperature": 0.8},
            },
            timeout=180,
        )

        content = response.json()["message"]["content"]
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            scripts = json.loads(content[start:end])
        except Exception:
            scripts = {"short": content[:500], "long": content}

        article["scripts"] = scripts

        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{week}/articles/scripts.json",
            Body=json.dumps(scripts, indent=2),
            ContentType="application/json",
        )

        return article


    # ── TASK 7a: Voice synthesis via Kokoro TTS ───────────────────────────────
    @task(
        task_id="synthesize_voice",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "1Gi",
                "request_cpu": "500m",
            }
        },
    )
    def synthesize_voice(article: dict, **context) -> str:
        """
        Send short script to Kokoro TTS, save MP3 to S3.
        Returns S3 key for audio file.
        """
        import requests
        import boto3
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        script_text = article["scripts"]["short"]

        # Kokoro TTS API (self-hosted, OpenAI-compatible endpoint)
        tts_response = requests.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json={
                "model": "kokoro",
                "input": script_text,
                "voice": "af_sky",   # available Kokoro voices: af_sky, af_bella, am_adam
                "response_format": "mp3",
            },
            timeout=120,
        )
        tts_response.raise_for_status()

        s3_key = f"{week}/audio/voice.mp3"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=tts_response.content,
            ContentType="audio/mpeg",
        )

        return s3_key


    # ── TASK 7b: AI video generation via RunwayML ─────────────────────────────
    @task(
        task_id="generate_ai_video",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "256Mi",
                "request_cpu": "100m",
            }
        },
    )
    def generate_ai_video(article: dict, **context) -> str:
        """
        Send a visual prompt to RunwayML Gen-3 API.
        Poll until video is ready, download and save to S3.
        Returns S3 key.
        """
        import requests
        import boto3
        import time
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")

        headers = {
            "Authorization": f"Bearer {RUNWAY_API_KEY}",
            "Content-Type": "application/json",
        }

        # Build a visual prompt from the article topic
        visual_prompt = (
            f"Cinematic tech visualization: {article['scripts']['short'][:200]}. "
            f"Modern data center, glowing code, clean and professional. 4K."
        )

        # Submit generation job to RunwayML
        gen_response = requests.post(
            "https://api.runwayml.com/v1/image_to_video",
            headers=headers,
            json={
                "promptText": visual_prompt,
                "model": "gen3a_turbo",
                "duration": 10,
                "ratio": "1280:768",
            },
            timeout=30,
        )
        gen_response.raise_for_status()
        task_id = gen_response.json()["id"]

        # Poll for completion
        for _ in range(60):  # max 10 minutes
            time.sleep(10)
            status_response = requests.get(
                f"https://api.runwayml.com/v1/tasks/{task_id}",
                headers=headers,
                timeout=15,
            )
            status_data = status_response.json()
            if status_data["status"] == "SUCCEEDED":
                video_url = status_data["output"][0]
                break
            elif status_data["status"] == "FAILED":
                raise Exception(f"RunwayML task failed: {status_data}")
        else:
            raise TimeoutError("RunwayML video generation timed out")

        # Download and upload to S3
        video_content = requests.get(video_url, timeout=60).content
        s3_key = f"{week}/video/raw/runway.mp4"
        boto3.client("s3").put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=video_content,
            ContentType="video/mp4",
        )

        return s3_key


    # ── TASK 8: Compose final video with FFmpeg ────────────────────────────────
    @task(
        task_id="compose_video",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "2Gi",
                "request_cpu": "2000m",
            }
        },
    )
    def compose_video(audio_key: str, video_key: str, **context) -> str:
        """
        Download audio + video from S3, combine with FFmpeg,
        generate short and long versions. Upload final to S3.
        """
        import subprocess
        import boto3
        import tempfile
        import os
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")
        s3 = boto3.client("s3")

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "voice.mp3")
            video_path = os.path.join(tmpdir, "raw.mp4")
            output_path = os.path.join(tmpdir, "final.mp4")

            s3.download_file(S3_BUCKET, audio_key, audio_path)
            s3.download_file(S3_BUCKET, video_key, video_path)

            # Combine video + audio, loop video to match audio length
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-stream_loop", "-1", "-i", video_path,
                    "-i", audio_path,
                    "-c:v", "libx264", "-c:a", "aac",
                    "-shortest",
                    "-vf", "scale=1080:1920",  # vertical for Reels/Shorts
                    output_path,
                ],
                check=True,
                timeout=300,
            )

            final_key = f"{week}/video/final/short.mp4"
            with open(output_path, "rb") as f:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=final_key,
                    Body=f.read(),
                    ContentType="video/mp4",
                )

        return final_key


    # ── TASK 9: Send to Telegram for review ───────────────────────────────────
    @task(
        task_id="notify_telegram",
        executor_config={
            "KubernetesExecutor": {
                "request_memory": "256Mi",
                "request_cpu": "100m",
            }
        },
    )
    def notify_telegram(article: dict, video_key: str, **context) -> None:
        """
        Download final video from S3 and send to Telegram.
        The Telegram bot (always-on deployment) handles the
        human approval loop independently via callback buttons.
        """
        import boto3
        import requests
        import tempfile
        import os
        from datetime import datetime

        week = datetime.now().strftime("%Y-%W")
        s3 = boto3.client("s3")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "final.mp4")
            s3.download_file(S3_BUCKET, video_key, video_path)

            caption = (
                f"*Week {week} content ready for review*\n\n"
                f"Fact check: {'PASSED' if article.get('fact_check_passed') else 'ISSUES FOUND'}\n"
                f"Issues: {len(article.get('fact_check_issues', []))}\n\n"
                f"Use buttons below to approve or request edits."
            )

            with open(video_path, "rb") as video_file:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                    data={
                        "chat_id": TELEGRAM_CHAT,
                        "caption": caption,
                        "parse_mode": "Markdown",
                        "reply_markup": '{"inline_keyboard": [['
                        '{"text": "Approve - Publish", "callback_data": "approve"},'
                        '{"text": "Edit", "callback_data": "edit"},'
                        '{"text": "Reject", "callback_data": "reject"}'
                        "]]}",
                    },
                    files={"video": video_file},
                    timeout=60,
                )


    # ── DAG wiring ────────────────────────────────────────────────────────────
    articles       = scrape_medium()
    research       = research_topics(articles)
    collection     = embed_and_store(research)
    article        = generate_article(collection)
    checked        = fact_check(article)
    scripted       = generate_video_script(checked)

    # Parallel: voice + AI video
    audio_key      = synthesize_voice(scripted)
    raw_video_key  = generate_ai_video(scripted)

    final_key      = compose_video(audio_key, raw_video_key)
    notify_telegram(scripted, final_key)
