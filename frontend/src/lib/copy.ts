export const COPY = {
  // Brand
  BRAND_NAME: "Satyum",
  BANK_NAME: "Canara Bank",
  HEADER_SUBTITLE: "Document Integrity Verification",
  
  // Navigation & Intake
  TAB_DOCUMENT: "Verify Document",
  TAB_BUNDLE: "Verify Bundle",
  TAB_CAMERA: "Live Capture",
  TAB_SAMPLE: "Sample Review",

  // Upload actions
  UPLOAD_DROP_TITLE: "Drop document to verify",
  UPLOAD_DROP_SUBTITLE: "Supports PDF, JPG, and PNG",
  UPLOAD_BUTTON: "Select Document",
  
  // Bundle actions
  BUNDLE_DROP_TITLE: "Drop related documents",
  BUNDLE_DROP_SUBTITLE: "e.g., ID and Bank Statement",
  BUNDLE_BUTTON: "Select Bundle",
  
  // Processing
  PROCESSING_TITLE: "Checking document...",
  PROCESSING_SUBTITLE: "Running structural and content verification.",
  
  // Verdict states (Human language, no "fail-closed")
  VERDICT_APPROVED_TITLE: "Verification Passed",
  VERDICT_APPROVED_DESC: "No tampering detected. Document structure is verified.",
  
  VERDICT_REVIEW_TITLE: "Manual Review Needed",
  VERDICT_REVIEW_DESC: "Unusual patterns detected. Please verify with applicant.",
  
  VERDICT_REJECTED_TITLE: "Verification Failed",
  VERDICT_REJECTED_DESC: "Signs of tampering or forgery detected.",
  
  // Footer
  FOOTER_SECURE: "Secured by Satyum. All processing is localized to this session.",
  
  // Camera specific
  CAMERA_READY: "Position document in frame",
  CAMERA_CAPTURE: "Capture Document",
  CAMERA_CHALLENGE: "Move camera slightly to verify",
} as const;
