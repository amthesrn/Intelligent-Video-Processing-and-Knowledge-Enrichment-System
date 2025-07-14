# Intelligent Video Processing and Knowledge Enrichment System

This repository contains a modular and scalable pipeline for converting YouTube-based AI research explanation videos into structured knowledge graphs, with support for semantic enrichment and Cypher-based question answering. The system leverages a multimodal MCP (Model Context Protocol) framework, Gemini LLM summarization, LangChain for entity extraction, and Neo4j for graph-based reasoning.

---

## 🧩 Key Features

- ✅ **Automated YouTube Video Processing:** Download videos using various filters like URL, channel ID, playlist, date range, and topic-wise selection.
- 🧠 **LLM-Based Summarization:** Use Gemini 2.0 Flash to convert video transcripts into structured, factual summaries.
- 🧾 **Metadata Handling:** Automatically collects and processes `metadata.json` and `transcript.txt` for each video.
- 🔍 **Entity Extraction and Relationship Mapping:** Extract key concepts and their relationships using LangChain with Jinja prompt.
- 🌐 **Neo4j Knowledge Graphs:** Create and enrich knowledge graphs using entity/relationship data and semantic similarity.
- 💬 **Q&A Support:** Answer natural language queries using LangChain’s CypherChain over the constructed Neo4j graph.

---

## 🔄 System Overview

### 📹 Intelligent Video Processing

This module handles automated collection of YouTube videos explaining AI research papers (published after Jan 2025) using the **MCP-based client-server architecture**.

- The **YouTube MCP Client** allows filtering and downloading videos by:
  - Video URL
  - Channel ID / Handle
  - Playlist URL
  - Date range (start–end)
  - Topic-wise filtering (AI, LLMs, Agents, etc.)

- The **MCP Server** manages multiple tools:
  - 📼 `video.mkv` – Video file for archival
  - 📝 `transcript.txt` – Auto-generated from audio
  - 📑 `metadata.json` – Includes title, description, channel info, etc.
  - 📄 `summary.json` – Generated using Gemini 2.0 Flash summarization API

Each folder represents a video and contains these four files, ready for downstream processing.

---

### 🧠 Knowledge Graph Construction and Enrichment

The second phase uses the `.json` summary output from the MCP pipeline:

1. **Text Conversion:** The `.json` summaries are converted into `.txt` format.
2. **Entity Recognition:** LangChain processes the summaries using prompt-based extraction (Jinja), identifying:
   - Named entities (technologies, datasets, models)
   - Semantic relations (e.g., "uses", "improves", "evaluates")
3. **Graph Creation:** Entities and relationships are pushed to a **Neo4j** instance, forming a structured knowledge graph.
4. **Enrichment:** Using FAISS-based similarity, new summaries are matched against existing nodes to:
   - Avoid duplicates
   - Enhance graph connectivity
5. **Q&A Evaluation:** The system supports question answering via LangChain’s `GraphCypherQAChain`, enabling users to ask factual questions and retrieve answers directly from the graph.

---

## 📁 Directory Structure

# Intelligent Video Processing and Knowledge Enrichment System

This project transforms research paper explanation videos into structured knowledge graphs using a modular multimodal processing pipeline integrated with Gemini LLM and Neo4j. It automates the ingestion, transcription, summarization, entity recognition, and knowledge enrichment using symbolic reasoning and LLM capabilities.

---

## 🚀 Project Overview

The system processes AI-focused YouTube videos—especially those explaining recent arXiv papers (post-Jan 2025)—and extracts structured knowledge in the form of knowledge graphs. It integrates the following:

- **YouTube Video Collection**
- **Gemini 2.0 Flash-based Summarization**
- **LangChain for Entity & Relationship Extraction**
- **Neo4j for Graph Storage & Querying**
- **Autogen-Enabled Client-Server Video Processing**

---

## 📁 Directory Structure

```bash
intelligent-video-kg/
├── README.md
├── requirements.txt
├── .gitignore
├── docs/
│   └── pipeline.png
│   ├── Project_Report.pdf
│   └── presentation.pptx
├── data/
│   └── dataset_in_drive.txt
├── prompts/
│   └── prompt.jinja
├── mcp/
│   ├── youtube_download_menudrive.py
│   ├── Youtube_mcp_server.py
│   └── YouTube_MCP_Autogen_based_client.py
├── kg_pipeline/
│   ├── knowledge_graph_code.ipynb
│   └── client_logger.py


## 🔄 Pipeline Flow

1. **YouTube Collection** → Download videos, transcript, metadata and  
   **Summarization** → LLM (Gemini 2.0 Flash) creates structured summaries with .jinja prompt
2. **Entity Recognition** → LangChain + prompt-based parsing
3. **Graph Construction** → Nodes and relationships written to Neo4j
4. **Enrichment** → Match + merge similar nodes using FAISS similarity
5. **QA Testing** → LangChain CypherChain queries + accuracy scoring


## 📦 Installation

Install dependencies:

```bash
pip install -r requirements.txt


## 👤 Author

**Soumya Ranjan Nayak**  
Project ID: 23070243063  
Department of Data Science and Spatial Analytics
[Symbiosis Institute of Geoinformatics]