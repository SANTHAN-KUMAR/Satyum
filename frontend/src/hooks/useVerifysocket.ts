import { useCallback, useEffect, useRef, useState } from "react";
import { liveVerifyUrl } from "@/api/client";
import { parseServerMessage } from "@/api/guards";
import type {
  ClientMessage,
  EvidencePackSignal,
  ServerChallengeMessage,
  TrustScore,
} from "@/api/types";

/**
 * Native WebSocket client for the live-capture pipeline (/ws/verify).
 *
 * Connects for REAL and reports the real connection state. If the backend route is not yet
 * implemented, the socket will fail/close and this hook surfaces "unreachable"/"closed" honestly —
 * it NEVER fabricates a challenge or per-tier status (CLAUDE.md §3.1/§3.4). The challenge instruction
 * and live signal statuses rendered by CameraCapture come ONLY from validated server messages.
 */
export type SocketState = "idle" | "connecting" | "open" | "closed" | "unreachable";

interface UseVerifySocketResult {
  state: SocketState;
  /** The active server-issued physical challenge, or null until/unless the server issues one. */
  challenge: ServerChallengeMessage | null;
  /** Live per-tier signal statuses, exactly as streamed by the server. */
  liveSignals: EvidencePackSignal[];
  /** The final TrustScore once the server concludes the live session. */
  result: TrustScore | null;
  /** The last honest notice/error string from the server or transport. */
  notice: string | null;
  connect: (docType: string | null) => void;
  disconnect: () => void;
  sendFrame: (jpegBase64: string) => void;
}

export function useVerifySocket(): UseVerifySocketResult {
  const [state, setState] = useState<SocketState>("idle");
  const [challenge, setChallenge] = useState<ServerChallengeMessage | null>(null);
  const [liveSignals, setLiveSignals] = useState<EvidencePackSignal[]>([]);
  const [result, setResult] = useState<TrustScore | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const everOpened = useRef(false);

  const cleanup = useCallback(() => {
    const ws = wsRef.current;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      wsRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    cleanup();
    setState("closed");
  }, [cleanup]);

  const send = useCallback((msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }, []);

  const connect = useCallback(
    (docType: string | null) => {
      cleanup();
      setChallenge(null);
      setLiveSignals([]);
      setResult(null);
      setNotice(null);
      everOpened.current = false;
      setState("connecting");

      let ws: WebSocket;
      try {
        ws = new WebSocket(liveVerifyUrl());
      } catch {
        setState("unreachable");
        setNotice("Could not open a connection to the live-verification service.");
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        everOpened.current = true;
        setState("open");
        send({ type: "hello", doc_type: docType });
      };

      ws.onmessage = (ev) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "");
        } catch {
          setNotice("Received a malformed message from the server (ignored).");
          return;
        }
        const msg = parseServerMessage(parsed);
        if (!msg) {
          setNotice("Received an unrecognised message from the server (ignored).");
          return;
        }
        switch (msg.type) {
          case "challenge":
            setChallenge(msg);
            break;
          case "tier_status":
            setLiveSignals(msg.signals);
            break;
          case "result":
            setResult(msg.trust_score);
            break;
          case "notice":
          case "error":
            setNotice(msg.message);
            break;
        }
      };

      ws.onerror = () => {
        // The browser fires error then close; we resolve the honest final state in onclose.
        if (!everOpened.current) setNotice("The live-verification socket reported a transport error.");
      };

      ws.onclose = () => {
        // If it never opened, the backend route is unreachable / not implemented — say so.
        setState(everOpened.current ? "closed" : "unreachable");
        if (!everOpened.current) {
          setNotice(
            "Could not reach /ws/verify. The live-capture backend is not available — no live data is shown.",
          );
        }
        wsRef.current = null;
      };
    },
    [cleanup, send],
  );

  const sendFrame = useCallback(
    (jpegBase64: string) => {
      send({
        type: "frame",
        challenge_id: challenge?.challenge_id ?? null,
        ts_ms: Date.now(),
        jpeg_base64: jpegBase64,
      });
    },
    [send, challenge],
  );

  useEffect(() => cleanup, [cleanup]);

  return { state, challenge, liveSignals, result, notice, connect, disconnect, sendFrame };
}
