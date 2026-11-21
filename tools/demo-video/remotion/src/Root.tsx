import React from "react";
import { Composition } from "remotion";
import { Abspann, Datenschutz, Titel, Ziele } from "./Cards";

// 1080p at 30 fps, like the screen recording. Durations are mirrored in polish.py (CARDS).
const FPS = 30;
const base = { fps: FPS, width: 1920, height: 1080 };
const sec = (s: number) => Math.round(s * FPS);

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Titel" component={Titel} durationInFrames={sec(5.5)} {...base} />
    <Composition id="Ziele" component={Ziele} durationInFrames={sec(10.8)} {...base} />
    <Composition id="Datenschutz" component={Datenschutz} durationInFrames={sec(6.6)} {...base} />
    <Composition id="Abspann" component={Abspann} durationInFrames={sec(5.6)} {...base} />
  </>
);
