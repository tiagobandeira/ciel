/**
 * mcp/whatsapp/bridge.js
 * ======================
 * Bridge mínimo WhatsApp ↔ Ciel usando Baileys.
 *
 * O que faz:
 *   - Conecta no WhatsApp via protocolo nativo (Baileys)
 *   - Exibe QR no terminal na primeira execução
 *   - Salva sessão em auth/ (não precisa reparear toda vez)
 *   - Recebe mensagens e envia via POST pro webhook do Ciel
 *   - Expõe POST /send e GET /status pro Ciel usar
 *
 * Uso:
 *   cd mcp/whatsapp
 *   npm install
 *   node bridge.js
 *
 * Variáveis de ambiente (opcionais):
 *   CIEL_WEBHOOK_URL   URL do webhook do Ciel (padrão: http://127.0.0.1:8766/webhook)
 *   BRIDGE_PORT        Porta HTTP do bridge   (padrão: 8765)
 *   LOG_LEVEL          Nível de log pino      (padrão: silent)
 */

import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} from "@whiskeysockets/baileys";
import qrcodeTerminal from "qrcode-terminal";
import express from "express";
import { fileURLToPath } from "url";
import path from "path";
import pino from "pino";

// ── config ────────────────────────────────────────────────────────────────────

const CIEL_WEBHOOK = process.env.CIEL_WEBHOOK_URL ?? "http://127.0.0.1:8766/webhook";
const BRIDGE_PORT  = parseInt(process.env.BRIDGE_PORT ?? "8765", 10);
const AUTH_DIR     = path.join(path.dirname(fileURLToPath(import.meta.url)), "auth");

// logger silencioso por padrão — o Baileys é bem verboso
const logger = pino({ level: process.env.LOG_LEVEL ?? "silent" });

// ── log com horário (mesmo estilo do log do bot) ──────────────────────────────

const ts  = () => new Date().toLocaleTimeString("pt-BR", { hour12: false });
const log = (msg) => console.log(`  ${ts()}  ${msg}`);

// ── estado global ─────────────────────────────────────────────────────────────

let sock       = null;
let status     = "disconnected";   // "disconnected" | "waiting_qr" | "connected"
let reconnects = 0;
const MAX_RECONNECTS = 10;


// ── envio pro webhook do Ciel (com retry) ─────────────────────────────────────
// Tenta até `attempts` vezes (espera 1s, 2s entre tentativas). Só loga quando
// falha de vez, pra não poluir o terminal.

async function notifyCiel(payload, attempts = 3) {
  for (let i = 1; i <= attempts; i++) {
    try {
      const res = await fetch(CIEL_WEBHOOK, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(payload),
      });
      if (!res.ok) log(`✗ webhook retornou ${res.status}`);
      return res.ok;
    } catch (err) {
      if (i === attempts) {
        log(`✗ Ciel indisponível (${err.cause?.code ?? err.message}), mensagem perdida`);
        return false;
      }
      await new Promise((r) => setTimeout(r, 1000 * i));
    }
  }
  return false;
}


// ── normaliza número pro formato +55 11 99999-9999 ───────────────────────────

function normalizeNumber(jid) {
  // jid: "5511999999999@s.whatsapp.net"  →  "+55 11 99999-9999"
  const digits = jid.replace(/@.+$/, "").replace(/\D/g, "");
  if (digits.length === 13 && digits.startsWith("55")) {
    // +55 (DD) 9XXXX-XXXX
    return `+${digits.slice(0, 2)} ${digits.slice(2, 4)} ${digits.slice(4, 9)}-${digits.slice(9)}`;
  }
  if (digits.length === 12 && digits.startsWith("55")) {
    // +55 (DD) XXXX-XXXX (fixo)
    return `+${digits.slice(0, 2)} ${digits.slice(2, 4)} ${digits.slice(4, 8)}-${digits.slice(8)}`;
  }
  return `+${digits}`;
}


// ── determina tipo de chat ────────────────────────────────────────────────────

function chatType(jid) {
  return jid.endsWith("@g.us") ? "group" : "direct";
}


// ── conecta ao WhatsApp ───────────────────────────────────────────────────────

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version }          = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    logger,
    auth: {
      creds: state.creds,
      keys:  makeCacheableSignalKeyStore(state.keys, logger),
    },
    printQRInTerminal: false,
    browser: ["Ciel Bot", "Chrome", "1.0.0"],
    syncFullHistory: false,       // não baixa histórico antigo
    markOnlineOnConnect: false,
  });

  // ── salva credenciais sempre que atualizar ────────────────────────────────
  sock.ev.on("creds.update", saveCreds);

  // ── status da conexão ─────────────────────────────────────────────────────
  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      status = "waiting_qr";
      console.log("\n[bridge] Escaneie o QR com o WhatsApp:\n");
      qrcodeTerminal.generate(qr, { small: true });
    }

    if (connection === "open") {
      status     = "connected";
      reconnects = 0;
      log("✓ WhatsApp conectado");
    }

    if (connection === "close") {
      status = "disconnected";
      const code = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = code !== DisconnectReason.loggedOut;

      if (shouldReconnect && reconnects < MAX_RECONNECTS) {
        reconnects++;
        const delay = Math.min(1000 * 2 ** reconnects, 30000); // backoff até 30s
        log(`reconectando em ${delay / 1000}s (tentativa ${reconnects})…`);
        setTimeout(connect, delay);
      } else if (code === DisconnectReason.loggedOut) {
        log("✗ Sessão encerrada. Apague auth/ e reinicie para reparear.");
      } else {
        log("✗ Número máximo de reconexões atingido.");
      }
    }
  });

  // ── mensagens recebidas ───────────────────────────────────────────────────
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;   // ignora sincronização de histórico

    for (const msg of messages) {
      const jid     = msg.key.remoteJid;
      const fromMe  = msg.key.fromMe ?? false;

      // extrai texto (texto simples, legenda de mídia, ou lista)
      const text = (
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        msg.message?.videoMessage?.caption ||
        msg.message?.listResponseMessage?.singleSelectReply?.selectedRowId ||
        ""
      ).trim();

      if (!text) continue;   // ignora mensagens sem texto (sticker, áudio, etc.)

      const payload = {
        chat_id:  jid,
        sender:   normalizeNumber(fromMe ? jid : (msg.key.participant ?? jid)),
        text,
        type:     chatType(jid),
        from_me:  fromMe,
        mentions: msg.message?.extendedTextMessage?.contextInfo?.mentionedJid ?? [],
      };

      // from_me não aparece no log (o bot descarta de qualquer jeito)
      if (!fromMe) {
        const preview = "";//text.length > 60 ? text.slice(0, 60) + "…" : text;
        log(`← ${payload.sender} (${payload.type})  ${preview}`);
      }

      await notifyCiel(payload);
    }
  });
}


// ── servidor HTTP ─────────────────────────────────────────────────────────────

const app = express();
app.use(express.json());

// GET /status — consultado pelo bot.py do Ciel
app.get("/status", (_req, res) => {
  res.json({ status });
});

// POST /send — chamado pelo Ciel pra enviar resposta
app.post("/send", async (req, res) => {
  const { chat_id, text } = req.body ?? {};

  if (!chat_id || !text) {
    return res.status(400).json({ error: "chat_id e text são obrigatórios" });
  }

  if (status !== "connected") {
    return res.status(503).json({ error: "WhatsApp não está conectado" });
  }

  try {
    await sock.sendMessage(chat_id, { text });
    log(`→ resposta enviada (${text.length} chars)`);
    res.json({ ok: true });
  } catch (err) {
    log(`✗ erro ao enviar: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

app.listen(BRIDGE_PORT, "127.0.0.1", () => {
  console.log(`[bridge] HTTP em 127.0.0.1:${BRIDGE_PORT}`);
  console.log(`[bridge] Webhook do Ciel: ${CIEL_WEBHOOK}`);
});


// ── inicia ────────────────────────────────────────────────────────────────────

console.log("[bridge] Iniciando conexão WhatsApp…");
connect();