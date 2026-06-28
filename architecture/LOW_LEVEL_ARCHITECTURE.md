# 🔐 Satyum — Low-Level Architecture

> **SuRaksha Cyber Hackathon 2.0 | Canara Bank**
> Layer-by-Layer Technical Deep Dive

> ⚠️ **SUPERSEDED (2026-06-27).** Describes the original *camera-only* design. Current authoritative
> architecture is **[ADR-001](ADR-001-dual-mode-and-signal-validity.md)** (dual-mode intake, mode-bound
> detectors, structural/semantic Layer 3). Several signals here are **cut or relabeled `NOT_EVALUATED`**
> on the camera path (ELA, steganalysis, JPEG copy-move, AI-gen, neural GradCAM, micro-tremor,
> hologram/microprint) and one is **cut entirely** (micro-expression). Use the surviving techniques
> (rectify/OCR/arithmetic-consistency/copy-move/pHash/active-challenge/anti-spoof) as reference only.

---

## Directory Structure

```
Satyum/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CameraCapture.jsx       ← WebRTC stream + frame extraction
│   │   │   ├── CaptchaChallenge.jsx    ← CAPTCHA instruction renderer
│   │   │   └── TrustScoreResult.jsx    ← Score display + flag details
│   │   ├── hooks/
│   │   │   └── useWebSocket.js         ← WS connection to backend
│   │   ├── App.jsx
│   │   └── main.jsx
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py                     ← FastAPI app entry point
│   │   ├── routes/
│   │   │   ├── session.py              ← POST /session/start, GET /session/{id}
│   │   │   └── verify.py              ← WebSocket /ws/verify
│   │   └── orchestrator.py             ← Calls all 5 layers, aggregates result
│   │
│   ├── services/
│   │   ├── capture_service.py          ← Layer 1: Anti-spoofing logic
│   │   ├── identity_service.py         ← Layer 2: Face liveness + deepfake
│   │   └── captcha_service.py          ← Layer 4: CAPTCHA generation & validation
│   │
│   ├── forensics/
│   │   ├── ela_analysis.py             ← Error Level Analysis
│   │   ├── copy_move_detector.py       ← SIFT/SURF based copy-move detection
│   │   ├── font_analyzer.py            ← Font consistency checks
│   │   └── ai_gen_detector.py          ← AI-generated content classification
│   │
│   ├── models/
│   │   ├── model_loader.py             ← Loads + caches all ML models at startup
│   │   ├── deepfake_model.py           ← FaceForensics++ or XceptionNet wrapper
│   │   └── ai_gen_model.py             ← CLIP / CNNDetect wrapper
│   │
│   └── risk/
│       └── risk_engine.py              ← Layer 5: Weighted scoring + explainability
│
└── infra/
    ├── docker-compose.yml
    ├── Dockerfile.backend
    ├── Dockerfile.frontend
    └── nginx/
        └── nginx.conf                  ← Reverse proxy + SSL termination
```

---

## Layer 1 — Capture Anti-Spoofing

**File:** `backend/services/capture_service.py`

**What it does:** Validates that the camera is looking at a real, physical document — not a screen, printout, or looped video.

### Detection Techniques

| Technique | Method | Target Attack |
|:---|:---|:---|
| **Moiré Pattern Detection** | FFT frequency analysis on frame | Printed document photos |
| **Screen Glare / Reflection** | Specular highlight detection via HSV | Phone/monitor screens |
| **Luma Uniformity** | Variance analysis across frame regions | Static looped video |
| **Frame Entropy Check** | Shannon entropy on consecutive frames | Static image / screenshot |
| **Shadow Geometry Check** 🌟 | Ambient shadow ray-casting consistency | Flat screens have no physical depth |
| **Chromatic Aberration Profiling** 🌟 | Per-channel (R/G/B) edge shift analysis | Camera lenses distort paper differently to displays |
| **Paper Texture FFT Fingerprint** 🌟 | 2D FFT spatial frequency peak analysis | Real paper grain has unique frequency cluster |

### 🌟 Shadow Geometry Check
Real 3D documents cast physically consistent shadows under ambient light. Flat digital displays have zero depth and cannot produce matching shadow geometry.
```
Detect ambient light direction from frame highlights
    │
    ▼
Estimate document surface plane (homography)
    │
    ▼
Project expected shadow vector from surface normal + light direction
    │
    ▼
Compare projected shadow with observed dark region in frame
    │
    ▼
Geometry mismatch beyond threshold → SCREEN FLAG
```

### 🌟 Chromatic Aberration Profiling
Camera lenses cause wavelength-dependent refraction (R/G/B channels shift slightly differently). This signature differs measurably between physical paper and a digital display surface.
```python
# Split frame into R, G, B channels
r, g, b = cv2.split(frame)

# Detect edges in each channel separately
edges_r = cv2.Canny(r, 50, 150)
edges_g = cv2.Canny(g, 50, 150)
edges_b = cv2.Canny(b, 50, 150)

# Measure lateral shift between edge positions across channels
shift_rg = compute_edge_shift(edges_r, edges_g)  # Expected: 0.5–2px for real paper
shift_gb = compute_edge_shift(edges_g, edges_b)

# Digital display: near-zero shift (pixel-perfect rendering)
# Physical paper: measurable shift from lens optics
if shift_rg < ABERRATION_THRESHOLD:
    flag("digital_display_detected")
```

### 🌟 Paper Texture FFT Fingerprint
Real paper has microscopic grain that produces a characteristic cluster in the 2D FFT frequency domain. Digital displays show a regular pixel grid pattern instead.
```python
import numpy as np

crop = frame[y:y+128, x:x+128, 0]  # Grayscale crop of document surface
f = np.fft.fft2(crop)
fshift = np.fft.fftshift(f)
magnitude = 20 * np.log(np.abs(fshift) + 1)

# Real paper: energy spread in mid-frequency bands (grain texture)
# Digital display: energy concentrated at regular pixel-grid frequencies
mid_freq_energy = magnitude[48:80, 48:80].mean()
if mid_freq_energy < PAPER_TEXTURE_THRESHOLD:
    flag("no_paper_texture")
```

### Input / Output
```python
# Input
frame: np.ndarray  # Single BGR frame from WebRTC stream

# Output
{
  "pass": bool,
  "confidence": float,       # 0.0 – 1.0
  "reason": str,             # e.g. "chromatic_aberration_low"
  "shadow_consistent": bool,
  "aberration_shift_px": float,
  "paper_texture_score": float
}

---

## Layer 2 — Identity Verification

**File:** `backend/services/identity_service.py`

**What it does:** Verifies a real, live human is holding the document — not a deepfake, AI-generated face, or static photo.

### Detection Techniques

| Technique | Method | Target Attack |
|:---|:---|:---|
| **rPPG Pulse Detection** | Facial colour micro-fluctuations (green channel) | Printed face, screen face |
| **Blink Detection** | Facial landmark tracking (dlib / MediaPipe) | Static photo |
| **Deepfake Detection** | XceptionNet / FaceForensics++ model | GAN / diffusion generated faces |
| **3D Depth Estimation** | Monocular depth estimation | 2D face photo |
| **Micro-tremor Analysis** 🌟 | Optical flow on document edges at 8–12 Hz | All digital displays |
| **Optical Flow Liveness** 🌟 | Dense Farnebäck flow aperiodicity check | Looped video replay |
| **Micro-expression Detection** 🌟 | 68-landmark Action Unit change analysis | Stress-free fraud presentations |

### rPPG Flow
```
Video frames (30fps minimum)
    │
    ▼
Detect facial region of interest (ROI)
    │
    ▼
Extract mean green channel pixel value per frame
    │
    ▼
Apply bandpass filter (0.7Hz – 4Hz = 42–240 BPM)
    │
    ▼
FFT → Extract dominant frequency
    │
    ▼
Valid heart rate range? → LIVENESS SCORE
```

### 🌟 Micro-tremor Analysis
Human hands holding documents have involuntary physiological tremors at 8–12 Hz (Parkinsonian range: 4–6 Hz, essential tremor: 8–12 Hz). Digital displays are perfectly rigid.
```python
# Track document corner points across 60 frames
corners = cv2.goodFeaturesToTrack(frame_gray, 50, 0.01, 10)
next_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, frame_gray, corners, None)

# Extract vertical displacement time-series for each tracked point
displacements = next_pts[status==1] - corners[status==1]

# FFT the displacement signal
freq_spectrum = np.abs(np.fft.rfft(displacements[:, 1]))  # Y-axis tremor
freqs = np.fft.rfftfreq(len(displacements), d=1/30)        # 30fps

# Check for energy in 8-12Hz band
tremor_band_energy = freq_spectrum[(freqs >= 8) & (freqs <= 12)].mean()
if tremor_band_energy < TREMOR_THRESHOLD:
    flag("no_physiological_tremor")  # Likely a digital display or rigid prop
```

### 🌟 Optical Flow Liveness
Natural paper movement from human breathing and hand micro-motion produces aperiodic, organic optical flow. Looped video replays produce perfectly cyclic, periodic flow patterns.
```python
flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None,
                                     0.5, 3, 15, 3, 5, 1.2, 0)
magnitude, angle = cv2.cartToPolar(flow[..., 0], flow[..., 1])

# Compute flow periodicity: FFT the magnitude time series
flow_series.append(magnitude.mean())
if len(flow_series) >= 90:  # 3 seconds
    spectrum = np.abs(np.fft.rfft(flow_series))
    peak_frequency = freqs[np.argmax(spectrum[1:])]  # Ignore DC
    if peak_frequency < 0.5:  # Very low freq dominant = looped video
        flag("periodic_optical_flow_detected")
```

### 🌟 Micro-expression Stress Detection
Involuntary sub-200ms facial Action Units (AU4: brow lowerer, AU7: lid tightener, AU17: chin raiser) fire during psychological stress and cannot be voluntarily suppressed.
```python
import mediapipe as mp

face_mesh = mp.solutions.face_mesh.FaceMesh()
results = face_mesh.process(rgb_frame)

# Extract key landmark deltas between consecutive frames
left_brow_delta = landmarks[70].y - prev_landmarks[70].y  # AU4
upper_lid_delta = landmarks[159].y - prev_landmarks[159].y  # AU7

# Flag if micro-expression duration < 200ms
if abs(left_brow_delta) > AU_THRESHOLD and expression_duration_ms < 200:
    stress_events.append(timestamp)
```

### Input / Output
```python
# Input
frames: List[np.ndarray]  # ~90 frames (3 seconds at 30fps)

# Output
{
  "liveness_score": float,         # 0.0 – 1.0
  "pulse_bpm": int,                # Detected BPM (0 if not detected)
  "tremor_score": float,           # 8-12Hz band energy
  "optical_flow_periodic": bool,   # True = looped video suspected
  "stress_events": int,            # Count of micro-expression events
  "deepfake_probability": float,
  "flags": List[str]
}

---

## Layer 3 — Document Forensics

**Files:** `backend/forensics/`

**What it does:** Analyzes the document image for signs of digital manipulation, AI generation, or physical forgery.

### Sub-Module: Error Level Analysis (ELA)
**File:** `forensics/ela_analysis.py`

ELA re-saves the JPEG at known quality and computes the difference. Areas that were edited retain higher error levels.

```
Original Frame
    │
    ▼
Re-save at 75% JPEG quality
    │
    ▼
Compute pixel-wise absolute difference
    │
    ▼
Normalize → Heatmap
    │
    ▼
Threshold high-variance regions → TAMPERING FLAG
```

### Sub-Module: Copy-Move Detection
**File:** `forensics/copy_move_detector.py`

- Extract keypoints using **SIFT or ORB**
- Match keypoints within same image
- Identify spatially displaced identical patches → copy-move flag

### Sub-Module: Font Analyzer
**File:** `forensics/font_analyzer.py`

- OCR the document (Tesseract or PaddleOCR)
- Cluster characters by detected font metrics (size, weight, spacing)
- Flag regions with inconsistent font metrics vs. rest of document

### Sub-Module: AI-Generated Content Detector
**File:** `forensics/ai_gen_detector.py`

- Use **CNNDetect** or **CLIP-based classifier** to determine if document image patches are AI-generated
- Output probability score per document region

### 🌟 Sub-Module: Steganographic Payload Detection
**File:** `forensics/stego_detector.py`

Detects hidden data injected into document pixels — a common technique in document laundering pipelines to embed machine-readable fake metadata.
```python
# LSB (Least Significant Bit) plane analysis
for channel in [r, g, b]:
    lsb_plane = channel & 1  # Extract lowest bit of each pixel
    entropy = shannon_entropy(lsb_plane)
    # Natural images: low LSB entropy (~0.5)
    # Stego payload: high LSB entropy (~1.0, looks random)
    if entropy > STEGO_ENTROPY_THRESHOLD:
        flag("lsb_stego_detected")

# DCT coefficient anomaly (JPEG steganography)
jpeg_coefficients = extract_dct_coefficients(image)
chi_square_stat = chi_square_test(jpeg_coefficients)
if chi_square_stat < 0.05:  # Statistically non-random DCT distribution
    flag("dct_stego_detected")
```

### 🌟 Sub-Module: GradCAM Explainability Heatmap
**File:** `forensics/gradcam.py`

Generates a visual heatmap showing exactly which pixels triggered the forgery classifier — providing auditor-grade explainability for bank compliance.
```python
import torch

class GradCAM:
    def __init__(self, model, target_layer):
        self.model = model
        self.target_layer = target_layer
        self.gradients = None
        target_layer.register_backward_hook(self._save_gradient)

    def _save_gradient(self, grad):
        self.gradients = grad

    def generate(self, input_tensor, class_idx):
        output = self.model(input_tensor)
        self.model.zero_grad()
        output[0, class_idx].backward()

        weights = self.gradients.mean(dim=[2, 3])     # Global average pool
        cam = (weights[:, :, None, None] * self.activations).sum(dim=1)
        cam = F.relu(cam)                              # Keep positive activations
        cam = F.interpolate(cam, size=input_tensor.shape[2:], mode='bilinear')
        return cam.squeeze().numpy()  # Heatmap overlay for frontend
```

### 🌟 Sub-Module: Neural Perceptual Hash (pHash)
**File:** `forensics/phash_engine.py`

Creates a compact 256-bit “document DNA” fingerprint using CNN embeddings. Enables cross-session fraud detection — catching the same forged document resubmitted days later.
```python
from imagehash import phash
from PIL import Image

# Generate perceptual hash of document region
doc_hash = phash(Image.fromarray(doc_crop), hash_size=16)  # 256-bit hash

# Compare against fraud database
for known_fraud_hash in fraud_db:
    hamming_distance = doc_hash - known_fraud_hash
    if hamming_distance <= PHASH_SIMILARITY_THRESHOLD:  # e.g., <= 8 bits
        flag("document_matches_known_fraud")
        return known_fraud_hash.session_id  # Cross-session trace
```

### Combined Output
```python
{
  "forensic_score": float,          # 0.0 – 1.0 (higher = more suspicious)
  "ela_flag": bool,
  "copy_move_flag": bool,
  "font_inconsistency_score": float,
  "ai_gen_probability": float,
  "stego_detected": bool,           # NEW
  "stego_method": str,              # "lsb" | "dct" | "none"
  "gradcam_heatmap": np.ndarray,    # NEW: pixel heatmap for frontend overlay
  "phash_match": bool,              # NEW: cross-session fraud match
  "phash_match_session_id": str,    # NEW: original session if match found
  "flags": List[str]
}

---

## Layer 4 — Physical CAPTCHA

**File:** `backend/services/captcha_service.py`

**What it does:** Issues a physical spatial challenge that can only be completed if a real document exists in real 3D space. Also harvests behavioral biometric signals and scans for document security features.

### Challenge Types

| Challenge | User Action | Validation |
|:---|:---|:---|
| **Tilt** | Tilt document to target angle | Camera-estimated pose angle ± 5° |
| **Proximity** | Move document closer | Bounding box size change > threshold |
| **Rotate** | Rotate document clockwise | Corner point homography tracking |
| **Cover** | Cover a specific corner | Region goes dark |

### 🌟 Behavioral Biometrics (Harvested During CAPTCHA)
While the user completes the CAPTCHA, Satyum secretly profiles their motion characteristics. Bots and automation tools move with unnatural mathematical precision; humans have natural jerk and velocity variation.
```python
# Track angular velocity of document during tilt challenge
angles = [estimate_tilt_angle(frame) for frame in captcha_frames]
angular_velocity = np.diff(angles)          # First derivative
angular_jerk = np.diff(angular_velocity)    # Second derivative (jerk)

# Human motion: smooth, variable jerk with overshoot/correction
# Bot motion: constant velocity, near-zero jerk, no overshoot
jerk_variance = np.var(angular_jerk)
if jerk_variance < HUMAN_JERK_THRESHOLD:
    flag("bot_like_motion_detected")

# Also compute: reaction time, correction count, motion smoothness
```

### 🌟 Security Feature Detection (Holograms & Microprinting)
Real bank documents contain physical security features: holograms (retroreflective), watermarks, and microprinting (sub-0.5mm text). Satyum detects their presence using specular highlight analysis.
```python
# Retroreflection analysis: as user tilts document, hologram regions
# produce characteristic specular highlight sweep
highlight_sweep = detect_specular_sweep_during_tilt(captcha_frames)
if not highlight_sweep.detected:
    flag("no_hologram_retroreflection")

# Microprinting: real documents have text at <0.5mm scale
# Detected via super-resolution upsampling + OCR on border regions
upsampled = cv2.resize(border_crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
micro_text = tesseract_ocr(upsampled, psm=6)
if len(micro_text.strip()) == 0:
    flag("no_microprinting_detected")
```

### Implementation Flow
```
Backend generates challenge (random type + target params)
    │
    ▼
Frontend renders instruction overlay on camera feed
    │
    ▼
User performs physical action
    │
    ▼
└─ Behavioral biometric profiling (background, silent)
└─ Security feature scan (hologram sweep, microprint)
└─ Challenge validation (pose / bbox / homography)
    │
    ▼
PASS / FAIL + behavioral_score + security_feature_flags
```

---

## Layer 5 — Risk Scoring Engine

**File:** `backend/risk/risk_engine.py`

**What it does:** Aggregates outputs from all 4 layers into a single weighted trust score with explainability.

### Scoring Weights

| Layer | Weight | Max Contribution |
|:---|:---|:---|
| Layer 1 — Capture Anti-Spoofing | 25% | 25 points |
| Layer 2 — Identity Verification | 30% | 30 points |
| Layer 3 — Document Forensics | 30% | 30 points |
| Layer 4 — Physical CAPTCHA | 15% | 15 points |
| **Total** | **100%** | **100 points** |

### Verdict Thresholds

| Score Range | Verdict |
|:---|:---|
| 85 – 100 | ✅ APPROVED |
| 60 – 84 | ⚠️ REVIEW (human review required) |
| 0 – 59 | ❌ REJECTED |

### Score Calculation
```python
def calculate_trust_score(layer_results: dict) -> dict:
    score = 0
    score += layer_results["capture"]["confidence"] * 25
    score += layer_results["identity"]["liveness_score"] * 30
    score += (1 - layer_results["forensics"]["forensic_score"]) * 30
    score += (1 if layer_results["captcha"]["pass"] else 0) * 15

    verdict = "APPROVED" if score >= 85 else "REVIEW" if score >= 60 else "REJECTED"
    return {"trust_score": round(score, 2), "verdict": verdict}
```

---

## Backend API Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/session/start` | Initializes a new verification session |
| `GET` | `/session/{id}` | Gets session status and result |
| `WS` | `/ws/verify` | WebSocket stream for real-time frame processing |
| `POST` | `/captcha/validate` | Validates CAPTCHA challenge response |

---

## Frontend — Key Technical Decisions

### WebRTC Camera Access
```javascript
const stream = await navigator.mediaDevices.getUserMedia({ video: true });
videoRef.current.srcObject = stream;
```

### Frame Extraction & Sending
```javascript
// Every 300ms, capture frame and send via WebSocket
const captureFrame = () => {
  ctx.drawImage(videoRef.current, 0, 0);
  canvas.toBlob(blob => ws.send(blob), 'image/jpeg', 0.8);
};
setInterval(captureFrame, 300);
```

### WebSocket Connection
```javascript
const ws = new WebSocket('wss://api.satyum.io/ws/verify');
ws.onmessage = (event) => {
  const result = JSON.parse(event.data);
  if (result.captcha_challenge) showCaptcha(result.captcha_challenge);
  if (result.final_score) showResult(result.final_score);
};
```

---

## Infrastructure

### Docker Compose Overview
```yaml
services:
  frontend:
    build: ./Dockerfile.frontend
    ports: ["3000:3000"]

  backend:
    build: ./Dockerfile.backend
    ports: ["8000:8000"]
    volumes:
      - ./models:/app/models   # ML model weights

  nginx:
    image: nginx:alpine
    ports: ["443:443", "80:80"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/ssl/certs
```

### Nginx Role
- **SSL termination** (HTTPS → HTTP internally)
- **Reverse proxy** (`/api/` → backend, `/ws/` → backend WebSocket, `/` → frontend)
- **Rate limiting** to prevent abuse

---

## Security Considerations

| Threat | Mitigation |
|:---|:---|
| Replay attack with recorded video | Frame entropy check + CAPTCHA challenge uniqueness |
| File upload bypass | System accepts only WebRTC streams, no file input endpoints |
| Model poisoning | Models loaded from read-only volume, not updated at runtime |
| DoS on inference | Rate limiting at Nginx + session token per request |
| Data leak | No frame persistence, all processing in-memory |

---

*Built for SuRaksha Cyber Hackathon 2.0 by Canara Bank*
