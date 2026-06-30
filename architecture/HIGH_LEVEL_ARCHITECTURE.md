# Satyum — High-Level Architecture

> **SUPERSEDED** — This document describes the v1 architecture. The authoritative design is
> [ADR-004 — v2 progressive evidence architecture](ADR-004-v2-progressive-evidence-architecture.md)
> (VLM understanding → canonical claim graph → deterministic decisioning). Kept for historical context only.

> **SuRaksha Cyber Hackathon 2.0 | Canara Bank**
> Theme 1: Real-Time Anomaly Detection in Financial Documents

> ⚠️ **SUPERSEDED (2026-06-27).** This document describes the original *camera-only* design. The
> architecture has since changed materially — see **[ADR-001](ADR-001-dual-mode-and-signal-validity.md)**
> for the current, authoritative design (dual-mode intake, mode-bound detectors, structural/semantic
> Layer 3, evidence-console framing). Treat the layer *mechanics* below as reference only; do **not**
> implement the camera-only flow, and do **not** run file-level forensics (ELA / stego / JPEG-copy-move /
> AI-gen / neural GradCAM) on the camera path.

---

## Overview

Satyum is a **zero-trust, camera-only document integrity verification platform** for banks. It detects forgery, tampering, deepfakes, and AI-generated content in financial documents — in real time, before anything enters the banking system.

**Core philosophy:** No file uploads. No trust by default. Documents are captured live via camera and analyzed through a 5-layer AI pipeline before a trust score is issued.

---

## Actors

| Actor | Role |
|:---|:---|
| **Bank Customer** | Submits document by holding it in front of a webcam |
| **Bank Staff / Portal** | Initiates the verification session via the frontend |
| **Satyum Platform** | Captures, analyzes, and returns a trust score |
| **Bank Core System** | Consumes the trust score decision via API to approve/reject |

---

## System Context Diagram

```
 Bank Customer (Browser / Webcam)
         │
         │ WebRTC Live Camera Stream
         ▼
 ┌─────────────────────────────────────┐
 │           FRONTEND                  │
 │   React + WebRTC                    │
 │   - Live camera capture UI          │
 │   - CAPTCHA challenge renderer      │
 │   - Trust score result display      │
 └────────────────┬────────────────────┘
                  │ HTTPS / WebSocket
                  ▼
 ┌─────────────────────────────────────┐
 │           BACKEND (FastAPI)         │
 │                                     │
 │  ┌──────────────────────────────┐   │
 │  │     Request Orchestrator     │   │
 │  └───┬──────────┬──────────┬───┘   │
 │      │          │          │        │
 │  [Layer 1]  [Layer 2]  [Layer 3]   │
 │  Capture    Identity   Document     │
 │  Anti-Spoof Verify     Forensics   │
 │      │          │          │        │
 │  [Layer 4]         [Layer 5]       │
 │  Physical CAPTCHA   Risk Scoring   │
 │                                     │
 └────────────────┬────────────────────┘
                  │
          ┌───────▼───────┐
          │  ML Models     │
          │  (loaded once) │
          └───────────────┘
                  │
          ┌───────▼───────┐
          │  INFRA         │
          │  Docker + Nginx│
          └───────────────┘
```

---

## The 5 Defence Layers

```
Incoming Camera Frame
        │
        ▼
┌───────────────────────────────────────────────┐
│ LAYER 1 — Capture Anti-Spoofing               │
│ Detects: Printed photos, phone/monitor screens│
│          looped video playback                 │
│ Output:  PASS / FAIL → abort if FAIL          │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ LAYER 2 — Identity Verification               │
│ Detects: Deepfake faces, AI-generated persons │
│          rPPG pulse detection (liveness check)│
│ Output:  LIVENESS SCORE → weighted to Layer 5 │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ LAYER 3 — Document Forensics                  │
│ Detects: Font inconsistencies, ELA tampering  │
│          Copy-move forgery, AI-gen content    │
│ Output:  FORENSIC SCORE → weighted to Layer 5 │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ LAYER 4 — Physical CAPTCHA                    │
│ Challenge: Tilt document 30°, move closer etc.│
│ Solvable only in real 3D physical space       │
│ Output:  CHALLENGE PASS / FAIL                │
└───────────────────────┬───────────────────────┘
                        ▼
┌───────────────────────────────────────────────┐
│ LAYER 5 — Risk Scoring Engine                 │
│ Aggregates all layer scores into weighted     │
│ final TRUST SCORE (0–100)                     │
│ Output: TRUST SCORE + explainable reason tags │
└───────────────────────────────────────────────┘
```

---

## Major Components

| Component | Technology | Purpose |
|:---|:---|:---|
| **Frontend** | React + WebRTC | Live camera capture, CAPTCHA UI, GradCAM heatmap overlay, result display |
| **Backend API** | FastAPI (Python) | Request orchestration, session management, REST + WebSocket |
| **Capture Service** | OpenCV + NumPy FFT | Anti-spoofing: moiré, shadow geometry, chromatic aberration, paper texture FFT |
| **Identity Service** | DeepFace / MediaPipe / rPPG | Liveness: rPPG pulse, micro-tremor, optical flow, micro-expression, deepfake |
| **Document Forensics** | PIL, scikit-image, PyTorch CNN | ELA, copy-move, font anomaly, AI-gen detection, steganography scan |
| **GradCAM Engine** | PyTorch hooks | Gradient-weighted heatmaps showing exact forgery pixels |
| **Neural pHash** | ImageHash / custom CNN embeddings | Perceptual document fingerprint for cross-session fraud matching |
| **CAPTCHA Service** | Geometry + Pose + IMU analysis | 3D spatial challenges + behavioral biometrics + security feature detection |
| **Risk Engine** | Custom weighted scorer | Aggregates all signals into final trust score with per-signal explainability |
| **ML Model Loader** | PyTorch / TensorFlow | Loads and caches all models at startup |
| **Infra** | Docker + Nginx | Containerization, reverse proxy, HTTPS termination |

---

## Signal Intelligence — What Makes Satyum Different

| Signal | Layer | Technique | Why It's Hard To Fake |
|:---|:---|:---|:---|
| **rPPG Pulse** | 2 | Green channel micro-fluctuation + bandpass FFT | Heartbeat signal cannot be replicated by a static image or looped video |
| **Micro-tremor** | 2 | Optical flow on document edge tracking (8–12 Hz) | Involuntary physiological hand tremor — absent in all digital displays |
| **Shadow Geometry** | 1 | Ambient shadow ray-casting consistency check | Real 3D paper casts physically consistent shadows; screens have no depth |
| **Chromatic Aberration** | 1 | Per-channel edge profile comparison (R/G/B shift) | Lens aberration signature is physically different for paper vs. display surfaces |
| **Paper Texture FFT** | 1 | 2D FFT of image crop — peak frequency analysis | Real paper grain produces a specific spatial frequency cluster not seen on screens |
| **Optical Flow Liveness** | 2 | Dense optical flow (Farnebäck) across frame sequence | Organic, aperiodic flow from real holding; looped video is perfectly cyclic |
| **Micro-expression** | 2 | 68-landmark AU (Action Unit) change detection | Sub-200ms stress expressions are involuntary and uncontrollable |
| **Steganography Scan** | 3 | LSB plane analysis + DCT coefficient anomaly detection | Detects hidden payloads often used in document laundering pipelines |
| **GradCAM Heatmap** | 3 | Backward gradient hooks on CNN forgery classifier | Visual pixel-level proof of *where* forgery occurred — explainable to bank auditors |
| **Neural pHash** | 3 | CNN embedding cosine distance across sessions | Document DNA — catches the same forged document submitted across multiple sessions |
| **Behavioral Biometrics** | 4 | Angular jerk, velocity profile during CAPTCHA motion | Bots move with unnatural precision; humans have natural angular jerk |
| **Security Feature Detection** | 4 | Retroreflection + specular highlight region analysis | Detects presence/absence of physical holograms and microprinting |

---

## Data Flow (Happy Path)

```
Customer holds document to webcam
        │
        ▼
WebRTC stream captured → sent to backend via WebSocket
        │
        ▼
Layer 1: Anti-spoof check → PASS
        │
        ▼
Layer 2: Face liveness check → PASS (pulse detected)
        │
        ▼
Layer 3: Document forensic scan → Minor flag (font variance)
        │
        ▼
Layer 4: CAPTCHA issued → Customer tilts document → PASS
        │
        ▼
Layer 5: Risk Engine calculates weighted score → 87/100
        │
        ▼
Response JSON → Bank's Core System → KYC Approved
```

---

## Data Classification & Privacy

| Data Type | Storage | Retention |
|:---|:---|:---|
| Live camera frames | In-memory only (never persisted) | Session lifetime only |
| Trust score result | Returned to bank system | Not stored by Satyum |
| ML Model weights | Local container volume | Persistent |
| Session metadata | In-memory | Request-scoped |

> **Satyum does NOT store** customer documents, images, or video frames. All processing is ephemeral and stateless.

---

## API Response Contract (Summary)

```json
{
  "session_id": "uuid",
  "trust_score": 87,
  "verdict": "APPROVED",
  "flags": ["minor_font_variance"],
  "explainability": {
    "layer_1_capture": "PASS",
    "layer_2_identity": "PASS",
    "layer_3_forensics": "WARN",
    "layer_4_captcha": "PASS",
    "layer_5_score": 87
  }
}
```

---

## Hackathon Phases

| Phase | Dates | Goal |
|:---|:---|:---|
| Idea Phase | Apr 29 – May 24, 2026 | Concept + Architecture submission |
| Prototype Phase | Jun 1 – Jun 30, 2026 | Working demo of core pipeline |

---

*Built for SuRaksha Cyber Hackathon 2.0 by Canara Bank*
