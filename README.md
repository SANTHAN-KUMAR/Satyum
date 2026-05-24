# 🔐 Satyum

### *No forgeries. Just truth.*

> **SuRaksha Cyber Hackathon 2.0 | Canara Bank**
> Theme 1: Real-Time Anomaly Detection in Financial Documents

---

## What is Satyum?

**Satyum** (सत्यम् = Truth, Absolute) is a zero-trust, camera-only document integrity verification platform for banks.

It detects forgery, tampering, deepfakes, and AI-generated content in land records, legal documents, and financial statements — in real time, before anything enters the banking system.

**No file uploads. No loopholes. Just truth.**

---

## Project Structure

```
Satyum/
├── docs/
│   ├── architecture/
│   │   ├── HIGH_LEVEL_ARCHITECTURE.md   ← System overview & component map
│   │   ├── LOW_LEVEL_ARCHITECTURE.md    ← Layer-by-layer technical deep dive
│   │   └── DATA_FLOW.md                 ← Happy path & attack path flows
│   ├── idea_submission/
│   │   └── IDEA_PHASE_SUBMISSION.md     ← Hackathon idea phase writeup
│   └── api/
│       └── API_CONTRACT.md              ← REST & WebSocket API reference
├── frontend/                            ← React + WebRTC frontend
├── backend/                             ← FastAPI Python backend
│   ├── app/                             ← Route handlers & orchestrator
│   ├── services/                        ← Capture, identity, CAPTCHA services
│   ├── forensics/                       ← Document analysis pipeline
│   └── models/                          ← ML model loaders
└── infra/                               ← Docker, Nginx config
```

---

## Five Defence Layers

| # | Layer | Core Signals |
|---|---|---|
| 1 | **Capture Anti-Spoofing** | Moiré FFT · Shadow geometry · Chromatic aberration profiling · Paper texture frequency fingerprint |
| 2 | **Identity Verification** | rPPG pulse · Micro-tremor physiological motion · Optical flow liveness · Micro-expression stress · Deepfake detection |
| 3 | **Document Forensics** | ELA tampering · Copy-move (SIFT) · Font inconsistency · AI-gen detection · Steganographic payload · GradCAM heatmap · Neural perceptual hash |
| 4 | **Physical CAPTCHA** | 3D spatial challenge · Behavioral biometrics · Document security feature detection (holograms, microprinting) |
| 5 | **Risk Scoring** | Weighted trust score · Explainable verdict · Per-layer flag breakdown |

---

## Signal Intelligence — What Makes Satyum Different

| Signal | Layer | Why It Matters |
|:---|:---|:---|
| **rPPG Pulse Detection** | 2 | Extracts heartbeat from facial skin-tone micro-fluctuations — impossible to fake with a photo or video |
| **Micro-tremor Analysis** | 2 | Human hands holding documents have involuntary 8–12 Hz physiological tremors; digital displays don't |
| **Shadow Geometry Check** | 1 | Real 3D documents cast physically consistent shadows under ambient light; flat screens cannot replicate this |
| **Chromatic Aberration Profiling** | 1 | Camera lenses bend light differently on physical paper vs. digital displays — unique spectral signature per surface type |
| **Paper Texture FFT Fingerprint** | 1 | Real paper grain has a specific spatial frequency signature detectable via Fast Fourier Transform |
| **Optical Flow Liveness** | 2 | Natural micro-movements of paper (breathing, hand tremor) produce organic optical flow; looped video is perfectly periodic |
| **Micro-expression Stress Detection** | 2 | Involuntary sub-200ms facial expressions betray psychological stress during document fraud attempts |
| **Steganographic Payload Detection** | 3 | Scans document pixels for hidden data embedded via LSB, DCT, or DWT steganography |
| **GradCAM Explainability Heatmap** | 3 | Gradient-weighted Class Activation Maps visually show exactly *which pixels* triggered a forgery flag |
| **Neural Perceptual Hash (pHash)** | 3 | Creates a document DNA fingerprint for cross-session fraud pattern matching |
| **Behavioral Biometrics** | 4 | Movement speed, jerk, and angular trajectory during CAPTCHA challenge reveal bot-like precision vs. natural human motion |
| **Security Feature Detection** | 4 | Detects holograms, watermarks, and microprinting via retroreflection and specular highlight analysis |

---

*Built for SuRaksha Cyber Hackathon 2.0 by Canara Bank*
