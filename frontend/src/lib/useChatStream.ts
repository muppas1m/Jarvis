"use client";

import { useCallback, useRef, useState } from "react";

import type { AgentState, ChatMessage, StreamEvent } from "./types";

/**
 * Consumes the BFF SSE stream (/api/chat/stream → backend stream_turn). Streams
 * tokens into the active assistant bubble for perceived latency, then reconciles
 * to the authoritative final text on `done`. Drives the orb's AgentState.
 */
export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [needsApproval, setNeedsApproval] = useState(false);
  const threadRef = useRef<string | null>(null);
  const busyRef = useRef(false);

  const patch = useCallback((id: string, content: string) => {
    setMessages((m) => m.map((x) => (x.id === id ? { ...x, content } : x)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busyRef.current) return;
      busyRef.current = true;
      setNeedsApproval(false);

      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
      const aiId = crypto.randomUUID();
      setMessages((m) => [...m, userMsg, { id: aiId, role: "assistant", content: "" }]);
      setAgentState("thinking");
      setActiveTool(null);

      try {
        const res = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, thread_id: threadRef.current }),
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let acc = "";
        let firstToken = true;

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const line = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            let ev: StreamEvent;
            try {
              ev = JSON.parse(line.slice(6)) as StreamEvent;
            } catch {
              continue;
            }
            switch (ev.type) {
              case "thread_id":
                threadRef.current = ev.content;
                break;
              case "token":
                if (firstToken) {
                  setAgentState("responding");
                  firstToken = false;
                }
                acc += ev.content;
                patch(aiId, acc);
                break;
              case "tool":
                setActiveTool(ev.content);
                break;
              case "approval_required":
                setNeedsApproval(true);
                patch(aiId, "⚠ Approval required — open the Approvals panel to decide.");
                break;
              case "done":
                patch(aiId, ev.content.response || acc);
                break;
              case "error":
                patch(aiId, `⚠ ${ev.content}`);
                break;
            }
          }
        }
      } catch {
        patch(aiId, "⚠ Could not reach Jarvis. Please try again.");
      } finally {
        busyRef.current = false;
        setAgentState("idle");
        setActiveTool(null);
      }
    },
    [patch],
  );

  return { messages, agentState, activeTool, needsApproval, send };
}
