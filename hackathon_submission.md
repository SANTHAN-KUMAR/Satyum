# Hackathon Submission Draft

## Title

**Satyum: Zero-Trust Document Integrity via Signal Intelligence**

---

## Description

**The Problem**
Current KYC and document verification systems rely on file uploads, making them highly vulnerable to digital tampering, deepfakes, and AI-generated forgeries. Once a forged document enters the banking system, the chain of trust is broken.

**The Solution: Satyum**
Satyum (सत्यम् = Truth) is a **zero-trust, camera-only document integrity platform** built for banks. We eliminate the "file upload" vulnerability entirely. Instead, customers present their documents live via a webcam. Satyum processes the WebRTC stream in real-time through a rigorous 5-layer AI defense pipeline, catching fraud before it ever hits the bank's core systems.

**No file uploads. No loopholes. Just truth.**

### 🌟 The "Wow Factors" — Signal Intelligence

Satyum doesn't just look at pixels; it analyzes the physics of the scene, physiological human traits, and microscopic document anomalies.

* **Physiological Micro-Tremor Analysis:** Human hands holding documents involuntarily tremor at 8–12 Hz. Satyum's optical flow tracks this; rigid digital displays (screens) fail instantly.
* **Shadow Geometry & Chromatic Aberration:** Real 3D paper casts ambient shadows and refracts light differently through a lens than a flat digital screen. We profile these optical physics to detect screen-spoofing.
* **rPPG Liveness & Micro-expressions:** We extract a live heartbeat (rPPG) from facial skin-tone fluctuations and detect sub-200ms involuntary stress micro-expressions (AUs) during fraud attempts.
* **GradCAM Explainability:** When forgery is detected, Satyum generates auditor-grade GradCAM heatmaps, visually proving *exactly which pixels* were manipulated.
* **Behavioral Biometrics & Security Scans:** During our physical 3D spatial CAPTCHA (e.g., "tilt the document"), we analyze angular jerk to detect bot-like precision, while scanning for retroreflective holograms and microprinting.
* **Neural pHash:** Every document gets a 256-bit "DNA" fingerprint. If a fraudster tries to launder and resubmit the same forged document in a different session, Satyum cross-matches it instantly.

### 🛡️ The 5-Layer Defense Pipeline

1. **Capture Anti-Spoofing:** Moiré FFT, shadow geometry, paper texture FFT.
2. **Identity Verification:** rPPG pulse, micro-tremors, deepfake detection.
3. **Document Forensics:** Error Level Analysis (ELA), Copy-Move, AI-gen detection, Steganography scan.
4. **Physical CAPTCHA:** 3D spatial challenges with behavioral biometric profiling.
5. **Risk Scoring:** Aggregates all signals into a final, explainable Trust Score (0-100).

### 🛠️ Tech Stack

* **Frontend:** React, WebRTC (Live Camera Stream)
* **Backend:** FastAPI (Python), WebSocket Orchestrator
* **AI/Forensics:** PyTorch, OpenCV, DeepFace, MediaPipe, NumPy FFT
* **Infrastructure:** Docker, Nginx
