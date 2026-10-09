import io
import os
from typing import Optional
import pypdf
import docx


POPULAR_JOB_DESCRIPTIONS = {
    "Full Stack Software Engineer": (
        "Role: Full Stack Software Engineer\n"
        "Core Responsibilities:\n"
        "- Design and implement scalable web applications across backend and frontend.\n"
        "- Build resilient REST and GraphQL APIs, integrate third-party services.\n"
        "- Collaborate on database modeling, queries optimization, and caching strategies.\n"
        "Requirements:\n"
        "- Proficient in modern frontend frameworks (React, Next.js, or Vue) and TypeScript.\n"
        "- Strong server-side engineering in Python (Django/FastAPI) or Node.js.\n"
        "- Experience with relational databases (PostgreSQL/MySQL) and Redis.\n"
        "- Familiarity with containerization (Docker), CI/CD pipelines, and cloud environments (AWS/GCP).\n"
        "- Understanding of distributed system design, clean architecture, and testing methodologies."
    ),
    "Backend Python / Django Developer": (
        "Role: Backend Python / Django Developer\n"
        "Core Responsibilities:\n"
        "- Build high-throughput, low-latency microservices and RESTful APIs.\n"
        "- Design complex data models, ORM queries, and asynchronous background tasks.\n"
        "- Maintain API security, authentication (JWT/OAuth), and tenant isolation.\n"
        "Requirements:\n"
        "- 3+ years writing clean, idiomatic Python.\n"
        "- Deep experience with Django, Django REST Framework, or FastAPI.\n"
        "- Proven track record with asynchronous processing (Celery, Redis, RabbitMQ).\n"
        "- Advanced PostgreSQL knowledge: indexing, transactions, and query optimization.\n"
        "- Strong testing discipline using pytest and CI/CD automation."
    ),
    "Frontend React / Next.js Engineer": (
        "Role: Frontend React / Next.js Engineer\n"
        "Core Responsibilities:\n"
        "- Develop interactive, accessible, and performant user interfaces.\n"
        "- Optimize Core Web Vitals, client-side rendering, and server-side rendering (SSR/SSG).\n"
        "- Maintain shared component libraries and state architecture.\n"
        "Requirements:\n"
        "- Mastery of modern React (Hooks, Context, Concurrent mode) and TypeScript.\n"
        "- Extensive experience with Next.js (App Router, Server Actions, SSR).\n"
        "- Proficiency with Tailwind CSS, modern state management (Zustand, Redux Toolkit, or TanStack Query).\n"
        "- Strong debugging skills for browser performance, DOM rendering, and API contracts."
    ),
    "AI & Machine Learning Engineer": (
        "Role: AI & Machine Learning Engineer\n"
        "Core Responsibilities:\n"
        "- Develop and deploy generative AI applications, agents, and RAG pipelines.\n"
        "- Fine-tune and evaluate LLMs on domain-specific datasets.\n"
        "- Build production-grade vector search and embeddings retrieval systems.\n"
        "Requirements:\n"
        "- Strong foundation in Python, PyTorch, or TensorFlow.\n"
        "- Hands-on experience with LLM orchestration frameworks (OpenAI SDK, LangChain, LlamaIndex).\n"
        "- Working knowledge of vector databases (Pinecone, Chroma, pgvector, Qdrant).\n"
        "- Understanding of prompt engineering, model evaluation, and inference latency optimization."
    ),
    "Cloud Architect & DevOps Engineer": (
        "Role: Cloud Architect & DevOps Engineer\n"
        "Core Responsibilities:\n"
        "- Architect highly available, resilient, multi-region cloud infrastructures on AWS/GCP.\n"
        "- Automate infrastructure deployment via Terraform, Ansible, and Kubernetes.\n"
        "- Implement robust observability, alerting, and incident response pipelines.\n"
        "Requirements:\n"
        "- Deep understanding of AWS/GCP core networking, IAM, VPC, and serverless architectures.\n"
        "- Experience with Kubernetes (EKS/GKE), Helm charts, and service meshes.\n"
        "- Hands-on mastery of Infrastructure as Code (Terraform or CloudFormation).\n"
        "- Solid scripting in Python, Bash, or Go."
    ),
}


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from PDF file bytes using pypdf."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        extracted_pages = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                extracted_pages.append(text.strip())
        return "\n\n".join(extracted_pages)
    except Exception as exc:
        return f"[Error parsing PDF: {str(exc)}]"


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from DOCX file bytes using python-docx."""
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as exc:
        return f"[Error parsing DOCX: {str(exc)}]"


def parse_resume_file(uploaded_file) -> str:
    """Parse an uploaded Django file object (PDF, DOCX, TXT) and return extracted text."""
    filename = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()

    if filename.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif filename.endswith(".docx"):
        return extract_text_from_docx(file_bytes)
    elif filename.endswith(".txt"):
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="replace")
    else:
        return "[Error: Unsupported file format. Please upload a PDF, DOCX, or TXT file.]"
