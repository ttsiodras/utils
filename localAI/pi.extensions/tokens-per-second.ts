/**
 * Tokens Per Second Extension
 *
 * Shows real-time token generation speed in the footer status bar
 * while pi is streaming. Uses the provider's usage.output from the
 * partial message for accurate token counts.
 */

import type { AssistantMessage } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const STATUS_KEY = "tps";
const RENDER_INTERVAL_MS = 250;

export default function (pi: ExtensionAPI) {
  let startTime: number | null = null;
  let lastRenderTime = 0;

  const getAssistantUsage = (msg: AssistantMessage): number => {
    return msg.role === "assistant" ? msg.usage.output : 0;
  };

  pi.on("agent_start", async (_event, ctx) => {
    startTime = null;
    ctx.ui.setStatus(STATUS_KEY, undefined);
  });

  pi.on("message_start", async (event, _ctx) => {
    if (event.message.role !== "assistant") return;
    startTime = Date.now();
    lastRenderTime = 0;
  });

  pi.on("message_update", async (event, ctx) => {
    if (!startTime || event.message.role !== "assistant") return;

    const now = Date.now();
    if (now - lastRenderTime < RENDER_INTERVAL_MS) return;
    lastRenderTime = now;

    const outputTokens = getAssistantUsage(event.message as AssistantMessage);
    if (outputTokens === 0) return;

    const elapsedSeconds = (now - startTime) / 1000;
    if (elapsedSeconds < 0.1) return;

    const tps = Math.round(outputTokens / elapsedSeconds);
    const tpsLabel = ctx.ui.theme.fg("accent", `${tps} tok/s`);
    const countLabel = ctx.ui.theme.fg("dim", `· ${outputTokens}`);
    ctx.ui.setStatus(STATUS_KEY, `${tpsLabel} ${countLabel}`);
  });

  pi.on("message_end", async (event, ctx) => {
    if (event.message.role !== "assistant" || !startTime) return;

    const outputTokens = getAssistantUsage(event.message as AssistantMessage);
    const elapsedSeconds = ((Date.now() - startTime) / 1000).toFixed(1);

    if (outputTokens > 0) {
      const tps = Math.round(outputTokens / parseFloat(elapsedSeconds));
      const tpsLabel = ctx.ui.theme.fg("success", `${tps} tok/s`);
      const countLabel = ctx.ui.theme.fg("dim", `· ${outputTokens} in ${elapsedSeconds}s`);
      ctx.ui.setStatus(STATUS_KEY, `${tpsLabel} ${countLabel}`);
    }

    startTime = null;
  });

  // pi.on("agent_end", async (_event, ctx) => {
  //   setTimeout(() => ctx.ui.setStatus(STATUS_KEY, undefined), 4000);
  // });
}
