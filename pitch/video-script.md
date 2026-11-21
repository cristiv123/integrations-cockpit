# Integrations-Cockpit – pitch video (≤ 2:00)

**The finished video:** `video/integrations-cockpit-pitch-en.mp4` (1:57, 1920×1080, English narration,
burned-in subtitles, music bed, −14 LUFS). Subtitles also as `video/pitch-subtitles-en.srt` (named so players
don't load it on top of the burned-in ones). `video/integrations-cockpit-demo-en.mp4` is the raw recording.

It is generated, not filmed by hand – with the app running on http://localhost:8501:

```
python tools/demo-video/build_slides.py      # deck slides as a local page
python tools/demo-video/tts.py en            # narration (Microsoft neural voice) + durations
node tools/demo-video/record.mjs --lang en   # headless Chrome drives the app and the slides
python tools/demo-video/compose.py en        # raw recording -> video/integrations-cockpit-demo-en.mp4
powershell tools/demo-video/render_cards.ps1 # animated cards (Remotion, node_modules from video-tools)
python tools/demo-video/polish.py en         # framed demo, push-ins, chapters, subtitles, music -> pitch MP4
```

The narration text is in `tools/demo-video/narration.json`. The table below is the plan it follows,
and still works as a script for a hand-made recording.

Screen recording of the running app (`streamlit run app.py`, synthetic demo data) with a voice-over.
About 280 words: read at a calm pace it lands at 1:50–1:55.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Deck slide 1 (cover) | The Asylsozialdienst of the City of Bern is paid only when a refugee reaches an integration goal – on time. Language, work, financial independence. Today nobody can see who is on track. |
| 0:12–0:27 | Sidebar: “Synthetische Demodaten”, then the 12 files in *Datenqualität* | Our Integrations-Cockpit works only with the Excel exports the service already has. Drop them in as they come – German column names, Swiss dates. It recognises every file and lists what is missing or wrong. |
| 0:27–0:47 | Tab *Cockpit*, scroll the matrix; switch goal 1 → 2 → 3 in the sidebar | For every client it computes the deadline for each goal and shows a traffic light: green reached, yellow on track, red at risk. The same for work, and for financial independence per household. |
| 0:47–1:05 | Role *Sozialarbeiter:in* → tab *Wen rufe ich an?* | A social worker opens it on Monday and gets a call list: red cases first, nearest deadline next, and the reason in plain words. |
| 1:05–1:18 | Role *Leitung* → *Datenqualität*, highlight “A1 fristgerecht nachgewiesen … Abgeltung prüfen: 24” | It also finds money: in our demo, 24 people proved A1 on time but the goal was never recorded – each one a payment to check. |
| 1:18–1:38 | Tab *Muster*: insights, then the chart for “Lateinisch alphabetisiert”; tab *Situationsanalysen* briefly | Level two asks why. It compares groups – never individuals, never groups under ten. Literacy in Latin script, schooling, motivation and psychological burden matter. Motivation and burden come from the free-text reports, read by an AI model that runs locally. |
| 1:38–1:50 | Sidebar button “Ergebnis als Excel”, open the file, show the *Cockpit* sheet | Everything goes back out as Excel, for daily work. Next month: same files, same clicks. |
| 1:50–2:00 | Deck slide 9 (data protection) | Nothing leaves the ASD network. Integrations-Cockpit – from Excel exports to “who do I call this week”. |

## Recording

- OBS Studio is installed: capture the browser window at 1920×1080, microphone on, export MP4.
- Hide the browser bookmarks bar; zoom the app to 110 % so tables stay readable.
- Say “demo data” once on screen or in the voice-over – none of these people are real.
- Upload as an unlisted video (or to a shared drive) and post the link in `#projects`, as the hackathon bot asks.

## Before recording

- Wait until the local LLM extraction has finished, then pick “LLM lokal” in the sidebar so the *Situationsanalysen* tab shows the measured accuracy.
- Restart the app once so every cache is fresh; the first load takes about 20 seconds.
