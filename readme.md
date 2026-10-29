
# 🛡️ Production Image Forensics & Attendance OCR API

A high-performance FastAPI backend designed for an attendance tracking system. It acts as a multi-layered security gatekeeper, validating the authenticity of user selfies by checking watermarks, extracting GPS data via Vision LLMs, scanning for editing software metadata, and detecting AI-generated images.

## 📑 Table of Contents
- [System Architecture & Flow](#-system-architecture--flow)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Environment Variables](#-environment-variables)
- [Local Setup & Installation](#️-local-setup--installation)
- [Running the Application](#-running-the-application)
- [API Documentation](#-api-documentation)
- [Deployment](#️-deployment-render)

---

## 🏗️ System Architecture & Flow

The system uses a **Gatekeeper Architecture** to save cost and processing time. It runs the cheapest, fastest validation first. If the image fails the OCR check, it short-circuits the process, avoiding expensive API calls entirely.

```mermaid
graph TD
    A[Client sends Image: Base64, URL, or Local Path] --> B[API: /validate-images]
    
    B --> C{Is Image Valid?}
    C -- No --> D[Return Error: File not found / Invalid format]
    C -- Yes --> E[Layer 1: OCR Extraction (Gemini 2.5 Flash-Lite)]
    
    E --> F{Watermark Valid? & Timestamp Valid?}
    
    F -- No --> G[Gatekeeper Triggered: Mark as INVALID IMAGE]
    G --> H[Skip AI & Forensics to save costs]
    H --> Z[Return Response to Client]
    
    F -- Yes --> I[Layer 2: Metadata Forensics]
    I --> J{Is Edited / Forged?}
    
    J -- Yes --> K[Flag: Edited Image]
    K --> Z
    J -- No --> L[Layer 3: AI Generation Detection (Sightengine)]
    
    L --> M{AI Score >= 0.40?}
    M -- Yes --> N[Flag: AI Generated]
    M -- No --> O[Flag: Original / Authentic]
    
    N --> Z
    O --> Z
