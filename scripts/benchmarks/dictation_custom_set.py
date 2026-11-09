"""Custom-vocabulary dictation set: sentences that contain names, product terms, and jargon, each with the target terms to be recovered.

Reference text is written the way a person would type it. Audio is synthesized with macOS `say`, so results bound accuracy from above (clean, consistent pronunciation) and are labeled synthetic wherever reported.
"""
from __future__ import annotations

from typing import List, Tuple

# (sentence id, voice, reference text, target terms that must appear in the transcript)
SENTENCES: List[Tuple[str, str, str, List[str]]] = [
    ("cv-01", "Samantha", "Please schedule a call with Siobhan Fitzgerald about the Kubernetes migration.", ["Siobhan", "Fitzgerald", "Kubernetes"]),
    ("cv-02", "Daniel", "The PostgreSQL replica lags behind the primary by about four seconds.", ["PostgreSQL"]),
    ("cv-03", "Karen", "Xavier Nguyen asked whether we can ship the Parakeet model with the next release.", ["Xavier", "Nguyen", "Parakeet"]),
    ("cv-04", "Alex", "We run llama.cpp with Metal acceleration on every Apple Silicon machine.", ["llama.cpp", "Metal"]),
    ("cv-05", "Moira", "Aoife O'Sullivan will present the OAuth rollout on Thursday.", ["Aoife", "O'Sullivan", "OAuth"]),
    ("cv-06", "Samantha", "The Sparkle update feed is signed with an EdDSA key.", ["Sparkle", "EdDSA"]),
    ("cv-07", "Daniel", "Open the Terraform plan and check the Datadog monitors for the staging cluster.", ["Terraform", "Datadog"]),
    ("cv-08", "Karen", "Basil keeps the knowledge base in SQLite on the local disk.", ["Basil", "SQLite"]),
    ("cv-09", "Alex", "Rajesh Venkataraman fixed the WebSocket reconnect bug in the FastAPI backend.", ["Rajesh", "Venkataraman", "WebSocket", "FastAPI"]),
    ("cv-10", "Moira", "The MCP server exposes a Slack search tool and a Gmail draft tool.", ["MCP", "Slack", "Gmail"]),
    ("cv-11", "Samantha", "Our SOC 2 audit covers Okta, Snowflake, and the Salesforce integration.", ["Okta", "Snowflake", "Salesforce"]),
    ("cv-12", "Daniel", "Gwyneth Pemberton reviewed the HIPAA language in the vendor agreement.", ["Gwyneth", "Pemberton", "HIPAA"]),
    ("cv-13", "Karen", "Use the Qwen model for tool calls and Whisper for the offline transcript.", ["Qwen", "Whisper"]),
    ("cv-14", "Alex", "The kubectl rollout restarted the Redis pods without any downtime.", ["kubectl", "Redis"]),
    ("cv-15", "Moira", "Dmitri Kowalczyk wants a GraphQL schema for the billing service.", ["Dmitri", "Kowalczyk", "GraphQL"]),
    ("cv-16", "Samantha", "The Homebrew cask pulls the signed DMG from GitHub Releases.", ["Homebrew", "DMG", "GitHub"]),
    ("cv-17", "Daniel", "Ngozi Adeyemi joined the Anthropic evaluation as the technical lead.", ["Ngozi", "Adeyemi", "Anthropic"]),
    ("cv-18", "Karen", "Check the Grafana dashboard before you touch the Nginx configuration.", ["Grafana", "Nginx"]),
    ("cv-19", "Alex", "Please add Tomasz Wisniewski to the Notion workspace and the Linear team.", ["Tomasz", "Wisniewski", "Notion", "Linear"]),
    ("cv-20", "Moira", "The Xcode build failed because the Swift package resolved an older Sparkle version.", ["Xcode", "Swift", "Sparkle"]),
    ("cv-21", "Samantha", "Ask Lucia Fernandez to export the CSV from Airtable and upload it to Dropbox.", ["Lucia", "Fernandez", "CSV", "Airtable", "Dropbox"]),
    ("cv-22", "Daniel", "The gRPC gateway talks to the Elasticsearch cluster over TLS.", ["gRPC", "Elasticsearch", "TLS"]),
    ("cv-23", "Karen", "Remind me to renew the Cloudflare certificate before the Zendesk migration.", ["Cloudflare", "Zendesk"]),
    ("cv-24", "Alex", "Mikhail Petrov benchmarked MLX against llama.cpp on the M5 Max.", ["Mikhail", "Petrov", "MLX", "llama.cpp"]),
    ("cv-25", "Moira", "The Playwright suite covers the Chrome and Safari login flows.", ["Playwright", "Chrome", "Safari"]),
    ("cv-26", "Samantha", "Priya Raghunathan owns the Jira board and the Confluence space.", ["Priya", "Raghunathan", "Jira", "Confluence"]),
    ("cv-27", "Daniel", "Run pytest with coverage and then lint with Ruff before pushing to main.", ["pytest", "Ruff"]),
    ("cv-28", "Karen", "The Apache license applies, and the trademark policy is separate.", ["Apache"]),
    ("cv-29", "Alex", "Beatriz Albuquerque approved the Stripe webhook change for the Vercel deployment.", ["Beatriz", "Albuquerque", "Stripe", "Vercel"]),
    ("cv-30", "Moira", "Our Kafka consumer group rebalanced after the Datadog alert fired.", ["Kafka", "Datadog"]),
]
