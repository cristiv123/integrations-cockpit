import React from "react";
import { AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadHead } from "@remotion/google-fonts/SpaceGrotesk";
import { loadFont as loadBody } from "@remotion/google-fonts/PublicSans";

const head = loadHead("normal", { weights: ["500", "700"], subsets: ["latin"] }).fontFamily;
const body = loadBody("normal", { weights: ["400", "600", "700"], subsets: ["latin"] }).fontFamily;

// Same palette as the pitch deck.
export const C = {
  navy: "#14213D",
  deep: "#0B1428",
  card: "#1D2C4F",
  ink: "#F6F4EF",
  soft: "#C9D3E3",
  peach: "#F2B98A",
  orange: "#E07A1F",
  red: "#D64534",
  amber: "#E2A82B",
  green: "#3C9A4A",
};

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Background: deep navy with a slowly drifting dot grid (deterministic: same frame, same image).
const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const step = 64;
  const dots = [];
  for (let y = 0; y < height + step; y += step) {
    for (let x = 0; x < width + step; x += step) {
      const k = `${x}-${y}`;
      const o = 0.04 + random(k) * 0.07;
      dots.push(
        <div key={k} style={{ position: "absolute", left: x - ((frame * 0.25) % step), top: y - ((frame * 0.15) % step),
          width: 3, height: 3, borderRadius: 3, background: C.soft, opacity: o }} />,
      );
    }
  }
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 35%, #1E3160, ${C.deep} 78%)` }}>
      {dots}
    </AbsoluteFill>
  );
};

const useFade = (inF = 10, outF = 12) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return Math.min(interpolate(frame, [0, inF], [0, 1], clamp), interpolate(frame, [durationInFrames - outF, durationInFrames], [1, 0], clamp));
};

const Rise: React.FC<{ delay: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ delay, children, style }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 18], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return <div style={{ opacity: p, transform: `translateY(${(1 - p) * 28}px)`, ...style }}>{children}</div>;
};

const Lights: React.FC<{ start: number; size?: number }> = ({ start, size = 34 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ display: "flex", gap: size * 0.65, justifyContent: "center" }}>
      {[C.red, C.amber, C.green].map((c, i) => {
        const s = spring({ frame: frame - start - i * 5, fps, config: { damping: 12, stiffness: 160 } });
        return <div key={c} style={{ width: size, height: size, borderRadius: size, background: c, transform: `scale(${s})`,
          boxShadow: `0 0 ${size}px ${c}aa` }} />;
      })}
    </div>
  );
};

const Eyebrow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontFamily: body, fontWeight: 700, fontSize: 26, letterSpacing: 5, color: C.peach }}>{children}</div>
);

export const Titel: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = useFade(8, 14);
  const t = spring({ frame: frame - 14, fps, config: { damping: 200 } });
  const rule = interpolate(frame, [30, 62], [0, 620], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Backdrop />
      <AbsoluteFill style={{ alignItems: "center", paddingTop: 230, textAlign: "center" }}>
        <Lights start={4} />
        <Rise delay={12} style={{ marginTop: 44 }}><Eyebrow>AI FOR ACCESS HACKATHON · BERN 2026</Eyebrow></Rise>
        <div style={{ fontFamily: head, fontWeight: 700, fontSize: 150, color: C.ink, marginTop: 18, letterSpacing: -2,
          transform: `translateY(${(1 - t) * 50}px)`, opacity: t }}>Integrations-Cockpit</div>
        <div style={{ width: rule, height: 3, background: C.peach, margin: "18px 0 30px" }} />
        <Rise delay={44}><div style={{ fontFamily: body, fontSize: 46, color: C.soft }}>From Excel exports to “who do I call this week, and why?”</div></Rise>
        <Rise delay={60} style={{ marginTop: 34 }}><div style={{ fontFamily: body, fontSize: 28, color: C.soft, opacity: 0.85 }}>Challenge by Stadt Bern, Asylsozialdienst</div></Rise>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const GOALS = [
  { n: "1", tag: "LANGUAGE", text: "A1 certificate within 3 years of entry", note: "VA and FL, 16+" },
  { n: "2", tag: "WORK", text: "6 months of work ≥ 60 %, or education Sek II / tertiary", note: "before end of responsibility" },
  { n: "3", tag: "INCOME", text: "12 months without social assistance", note: "whole household, before end of responsibility" },
];

export const Ziele: React.FC = () => {
  const frame = useCurrentFrame();
  const fade = useFade(8, 12);
  const last = interpolate(frame, [230, 252], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Backdrop />
      <AbsoluteFill style={{ padding: "140px 150px 0" }}>
        <Rise delay={4}><Eyebrow>THE CHALLENGE</Eyebrow></Rise>
        <Rise delay={10} style={{ marginTop: 16 }}>
          <div style={{ fontFamily: head, fontWeight: 700, fontSize: 70, color: C.ink, lineHeight: 1.08 }}>Paid only when a goal is reached – on time</div>
        </Rise>
        <div style={{ display: "flex", gap: 36, marginTop: 64 }}>
          {GOALS.map((g, i) => {
            const d = 34 + i * 22;
            const bar = interpolate(frame, [d + 6, d + 30], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
            return (
              <Rise key={g.n} delay={d} style={{ flex: 1, display: "flex" }}>
                <div style={{ flex: 1, background: C.card, borderRadius: 22, padding: "38px 40px 42px", boxSizing: "border-box",
                  position: "relative", overflow: "hidden", boxShadow: "0 24px 60px rgba(0,0,0,0.35)" }}>
                  <div style={{ position: "absolute", left: 0, top: 0, height: 6, width: `${bar * 100}%`, background: C.peach }} />
                  <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
                    <div style={{ fontFamily: head, fontWeight: 700, fontSize: 88, color: C.peach, lineHeight: 1 }}>{g.n}</div>
                    <div style={{ fontFamily: body, fontWeight: 700, fontSize: 26, letterSpacing: 4, color: C.peach }}>{g.tag}</div>
                  </div>
                  <div style={{ fontFamily: body, fontWeight: 600, fontSize: 36, color: C.ink, lineHeight: 1.3, marginTop: 22 }}>{g.text}</div>
                  <div style={{ fontFamily: body, fontSize: 27, color: C.soft, marginTop: 16 }}>{g.note}</div>
                </div>
              </Rise>
            );
          })}
        </div>
        <div style={{ marginTop: 54, opacity: last, transform: `translateY(${(1 - last) * 20}px)`, display: "flex", alignItems: "center", gap: 22 }}>
          <div style={{ width: 22, height: 22, borderRadius: 22, background: "#7C8799" }} />
          <div style={{ fontFamily: head, fontWeight: 500, fontSize: 46, color: C.ink }}>Today, nobody can see who is on track.</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Check: React.FC<{ p: number }> = ({ p }) => (
  <svg width={52} height={52} viewBox="0 0 52 52" style={{ flex: "none" }}>
    <circle cx={26} cy={26} r={24} fill={C.green} opacity={p} />
    <path d="M15 27 l8 8 l15 -17" fill="none" stroke={C.ink} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round"
      strokeDasharray={40} strokeDashoffset={40 * (1 - p)} />
  </svg>
);

const PRIVACY = [
  "Runs on one computer, in memory – nothing is stored",
  "The AI model runs locally; names and numbers are removed first",
  "Social workers see their own cases; patterns only for groups of 10+",
];

export const Datenschutz: React.FC = () => {
  const frame = useCurrentFrame();
  const fade = useFade(8, 12);
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Backdrop />
      <AbsoluteFill style={{ padding: "170px 190px 0" }}>
        <Rise delay={4}><Eyebrow>DATA PROTECTION BY DESIGN · revDSG</Eyebrow></Rise>
        <Rise delay={10} style={{ marginTop: 16 }}>
          <div style={{ fontFamily: head, fontWeight: 700, fontSize: 84, color: C.ink }}>Nothing leaves the network</div>
        </Rise>
        <div style={{ marginTop: 60, display: "flex", flexDirection: "column", gap: 34 }}>
          {PRIVACY.map((t, i) => {
            const d = 26 + i * 16;
            const p = interpolate(frame, [d, d + 16], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
            return (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: 30, opacity: p, transform: `translateX(${(1 - p) * -30}px)` }}>
                <Check p={p} />
                <div style={{ fontFamily: body, fontSize: 42, color: C.ink }}>{t}</div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const Abspann: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = useFade(8, 22);
  const t = spring({ frame: frame - 8, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Backdrop />
      <AbsoluteFill style={{ alignItems: "center", paddingTop: 250, textAlign: "center" }}>
        <Lights start={2} size={30} />
        <div style={{ fontFamily: head, fontWeight: 700, fontSize: 124, color: C.ink, marginTop: 40, opacity: t,
          transform: `translateY(${(1 - t) * 40}px)` }}>Integrations-Cockpit</div>
        <Rise delay={18} style={{ marginTop: 14 }}><div style={{ fontFamily: body, fontSize: 44, color: C.peach }}>From Excel exports to “who do I call this week?”</div></Rise>
        <Rise delay={32} style={{ marginTop: 70 }}><div style={{ fontFamily: body, fontSize: 30, color: C.soft }}>Team IntegrationCockpit · AI for Access Hackathon Bern 2026</div></Rise>
        <Rise delay={40} style={{ marginTop: 14 }}><div style={{ fontFamily: body, fontSize: 24, color: C.soft, opacity: 0.8 }}>Demo with synthetic data – no real people · Music: “Documentary” by AtlasAudio (Pixabay)</div></Rise>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
